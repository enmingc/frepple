#
# Copyright (C) 2007-2013 by frePPLe bv
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero
# General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from datetime import datetime
from dateutil.parser import parse
import json

from django.conf import settings
from django.contrib.admin.utils import unquote, quote
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import FieldDoesNotExist
from django.db import connections
from django.db.models.functions import Cast
from django.db.models import Q, F, FloatField, DateTimeField, DurationField
from django.db.models.expressions import RawSQL
from django.db.models.fields import CharField
from django.http import HttpResponse, Http404
from django.http.response import StreamingHttpResponse, HttpResponseServerError
from django.shortcuts import redirect
from django.template import Template
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ungettext
from django.utils.encoding import force_text
from django.utils.text import format_lazy
from django.views.generic import View
from django.views.decorators.csrf import csrf_exempt

from freppledb.boot import getAttributeFields
from freppledb.common.models import Parameter
from freppledb.input.models import (
    Resource,
    Operation,
    Location,
    SetupMatrix,
    SetupRule,
    Skill,
    Buffer,
    Customer,
    Demand,
    DeliveryOrder,
    Item,
    OperationResource,
    OperationMaterial,
    Calendar,
    CalendarBucket,
    ManufacturingOrder,
    SubOperation,
    ResourceSkill,
    Supplier,
    ItemSupplier,
    searchmode,
    OperationPlan,
    ItemDistribution,
    DistributionOrder,
    PurchaseOrder,
    OperationPlanMaterial,
    OperationPlanResource,
)
from freppledb.common.report import (
    GridReport,
    GridFieldBool,
    GridFieldLastModified,
    GridFieldDateTime,
    GridFieldTime,
    GridFieldText,
    GridFieldHierarchicalText,
    GridFieldNumber,
    GridFieldInteger,
    GridFieldCurrency,
    GridFieldChoice,
    GridFieldDuration,
    GridFieldJSON,
)
from .utils import OperationPlanMixin
from freppledb.admin import data_site

import logging

logger = logging.getLogger(__name__)


class SetupMatrixList(GridReport):
    title = _("setup matrices")
    basequeryset = SetupMatrix.objects.all()
    model = SetupMatrix
    frozenColumns = 1
    help_url = "model-reference/setup-matrices.html"

    rows = (
        GridFieldText(
            "name",
            title=_("name"),
            key=True,
            formatter="detail",
            extra='"role":"input/setupmatrix"',
        ),
        GridFieldText("source", title=_("source"), initially_hidden=True),
        GridFieldLastModified("lastmodified"),
    )


class SetupRuleList(GridReport):
    title = _("setup rules")
    basequeryset = SetupRule.objects.all()
    model = SetupRule
    frozenColumns = 1
    help_url = "model-reference/setup-matrices.html"

    rows = (
        GridFieldInteger(
            "id",
            title=_("identifier"),
            key=True,
            formatter="detail",
            extra='"role":"input/setuprule"',
            initially_hidden=True,
        ),
        GridFieldText(
            "setupmatrix",
            title=_("setup matrix"),
            field_name="setupmatrix__name",
            formatter="detail",
            extra='"role":"input/setupmatrix"',
        ),
        GridFieldInteger("priority", title=_("priority")),
        GridFieldText("fromsetup", title=_("from setup")),
        GridFieldText("tosetup", title=_("to setup")),
        GridFieldDuration("duration", title=_("duration")),
        GridFieldCurrency("cost", title=_("cost"), initially_hidden=True),
        GridFieldText(
            "resource",
            title=_("resource"),
            formatter="detail",
            extra='"role":"input/resource"',
            initially_hidden=True,
        ),
        GridFieldLastModified("lastmodified"),
    )


class ResourceList(GridReport):
    title = _("resources")
    basequeryset = Resource.objects.all()
    model = Resource
    frozenColumns = 1
    help_url = "modeling-wizard/manufacturing-capacity/resources.html"

    rows = (
        GridFieldText(
            "name",
            title=_("name"),
            key=True,
            formatter="detail",
            extra='"role":"input/resource"',
        ),
        GridFieldText("description", title=_("description")),
        GridFieldText("category", title=_("category"), initially_hidden=True),
        GridFieldText("subcategory", title=_("subcategory"), initially_hidden=True),
        GridFieldHierarchicalText(
            "location",
            title=_("location"),
            field_name="location__name",
            formatter="detail",
            extra='"role":"input/location"',
            model=Location,
        ),
        GridFieldText(
            "owner",
            title=_("owner"),
            field_name="owner__name",
            formatter="detail",
            extra='"role":"input/resource"',
            initially_hidden=True,
        ),
        GridFieldChoice("type", title=_("type"), choices=Resource.types),
        GridFieldBool("constrained", title=_("constrained")),
        GridFieldNumber("maximum", title=_("maximum")),
        GridFieldText(
            "maximum_calendar",
            title=_("maximum calendar"),
            field_name="maximum_calendar__name",
            formatter="detail",
            extra='"role":"input/calendar"',
        ),
        GridFieldText(
            "available",
            title=_("available"),
            field_name="available__name",
            formatter="detail",
            extra='"role":"input/calendar"',
        ),
        GridFieldCurrency("cost", title=_("cost"), initially_hidden=True),
        GridFieldDuration("maxearly", title=_("maxearly"), initially_hidden=True),
        GridFieldText(
            "setupmatrix",
            title=_("setup matrix"),
            field_name="setupmatrix__name",
            formatter="detail",
            extra='"role":"input/setupmatrix"',
            initially_hidden=True,
        ),
        GridFieldText("setup", title=_("setup"), initially_hidden=True),
        GridFieldText("source", title=_("source"), initially_hidden=True),
        # Translator: xgettext:no-python-format
        GridFieldNumber("efficiency", title=_("efficiency %"), formatter="percentage"),
        GridFieldText(
            "efficiency_calendar",
            # Translator: xgettext:no-python-format
            title=_("efficiency % calendar"),
            initially_hidden=True,
            field_name="efficiency_calendar__name",
            formatter="detail",
            extra='"role":"input/calendar"',
        ),
        GridFieldLastModified("lastmodified"),
        # Optional fields referencing the location
        GridFieldText(
            "location__description",
            title=format_lazy("{} - {}", _("location"), _("description")),
            initially_hidden=True,
            editable=False,
        ),
        GridFieldText(
            "location__category",
            title=format_lazy("{} - {}", _("location"), _("category")),
            initially_hidden=True,
            editable=False,
        ),
        GridFieldText(
            "location__subcategory",
            title=format_lazy("{} - {}", _("location"), _("subcategory")),
            initially_hidden=True,
            editable=False,
        ),
        GridFieldText(
            "location__available",
            title=format_lazy("{} - {}", _("location"), _("available")),
            initially_hidden=True,
            field_name="location__available__name",
            formatter="detail",
            extra='"role":"input/calendar"',
            editable=False,
        ),
        GridFieldText(
            "location__owner",
            title=format_lazy("{} - {}", _("location"), _("owner")),
            initially_hidden=True,
            field_name="location__owner__name",
            formatter="detail",
            extra='"role":"input/location"',
            editable=False,
        ),
        GridFieldText(
            "location__source",
            title=format_lazy("{} - {}", _("location"), _("source")),
            initially_hidden=True,
            editable=False,
        ),
        GridFieldLastModified(
            "location__lastmodified",
            title=format_lazy("{} - {}", _("location"), _("last modified")),
            initially_hidden=True,
            editable=False,
        ),
    )


class SkillList(GridReport):
    title = _("skills")
    basequeryset = Skill.objects.all()
    model = Skill
    frozenColumns = 1
    help_url = "model-reference/skills.html"

    rows = (
        GridFieldText(
            "name",
            title=_("name"),
            key=True,
            formatter="detail",
            extra='"role":"input/skill"',
        ),
        GridFieldText("source", title=_("source"), initially_hidden=True),
        GridFieldLastModified("lastmodified"),
    )


class ResourceSkillList(GridReport):
    title = _("resource skills")
    basequeryset = ResourceSkill.objects.all()
    model = ResourceSkill
    frozenColumns = 1
    help_url = "model-reference/resource-skills.html"

    rows = (
        GridFieldInteger(
            "id",
            title=_("identifier"),
            key=True,
            formatter="detail",
            extra='"role":"input/resourceskill"',
        ),
        GridFieldHierarchicalText(
            "resource",
            title=_("resource"),
            field_name="resource__name",
            formatter="detail",
            extra='"role":"input/resource"',
            model=Resource,
        ),
        GridFieldText(
            "skill",
            title=_("skill"),
            field_name="skill__name",
            formatter="detail",
            extra='"role":"input/skill"',
        ),
        GridFieldDateTime(
            "effective_start", title=_("effective start"), initially_hidden=True
        ),
        GridFieldDateTime(
            "effective_end", title=_("effective end"), initially_hidden=True
        ),
        GridFieldInteger("priority", title=_("priority"), initially_hidden=True),
        GridFieldText("source", title=_("source"), initially_hidden=True),
        GridFieldLastModified("lastmodified"),
    )


class ResourceDetail(OperationPlanMixin, GridReport):
    template = "input/operationplanreport.html"
    title = _("resource detail")
    model = OperationPlanResource
    permissions = (("view_resource_report", "Can view resource report"),)
    frozenColumns = 3
    editable = True
    multiselect = True
    height = 250
    help_url = "user-interface/plan-analysis/resource-detail-report.html"

    @classmethod
    def basequeryset(reportclass, request, *args, **kwargs):
        if args and args[0]:
            try:
                res = Resource.objects.using(request.database).get(name__exact=args[0])
                base = OperationPlanResource.objects.filter(
                    resource__lft__gte=res.lft, resource__rght__lte=res.rght
                )
            except OperationPlanResource.DoesNotExist:
                base = OperationPlanResource.objects.filter(resource__exact=args[0])
        else:
            base = OperationPlanResource.objects
        base = reportclass.operationplanExtraBasequery(base, request)
        return base.select_related().annotate(
            opplan_duration=RawSQL(
                "(operationplan.enddate - operationplan.startdate)", []
            ),
            opplan_net_duration=RawSQL(
                "(operationplan.enddate - operationplan.startdate - coalesce((operationplan.plan->>'unavailable')::int * interval '1 second', interval '0 second'))",
                [],
            ),
            setup_end=RawSQL("(operationplan.plan->>'setupend')", []),
            setup_duration=RawSQL("(operationplan.plan->>'setup')", []),
            feasible=RawSQL(
                "coalesce((operationplan.plan->>'feasible')::boolean, true)", []
            ),
        )

    @classmethod
    def initialize(reportclass, request):
        if reportclass._attributes_added != 2:
            reportclass._attributes_added = 2
            # Adding custom operation attributes
            for f in getAttributeFields(
                Operation, related_name_prefix="operationplan__operation"
            ):
                f.editable = False
                reportclass.rows += (f,)
            # Adding custom resource attributes
            for f in getAttributeFields(Resource, related_name_prefix="resource"):
                f.editable = False
                reportclass.rows += (f,)

    @classmethod
    def extra_context(reportclass, request, *args, **kwargs):
        if args and args[0]:
            request.session["lasttab"] = "plandetail"
            return {
                "active_tab": "plandetail",
                "model": Resource,
                "title": force_text(Resource._meta.verbose_name) + " " + args[0],
                "post_title": _("plan detail"),
            }
        else:
            return {"active_tab": "plandetail", "model": OperationPlanResource}

    rows = (
        GridFieldInteger(
            "id",
            title="identifier",
            key=True,
            editable=False,
            formatter="detail",
            extra='"role":"input/operationplanresource"',
            initially_hidden=True,
        ),
        GridFieldText(
            "resource",
            title=_("resource"),
            field_name="resource__name",
            formatter="detail",
            extra='"role":"input/resource"',
        ),
        GridFieldText("operationplan__reference", title=_("reference"), editable=False),
        GridFieldText(
            "owner",
            title=_("owner"),
            field_name="operationplan__owner__reference",
            formatter="detail",
            extra="role:'input/manufacturingorder'",
            initially_hidden=True,
        ),
        GridFieldText(
            "color",
            title=_("inventory status"),
            formatter="color",
            field_name="operationplan__color",
            width="125",
            editable=False,
            extra='"formatoptions":{"defaultValue":""}, "summaryType":"min"',
        ),
        GridFieldText(
            "operationplan__item",
            title=_("item"),
            editable=False,
            formatter="detail",
            extra='"role":"input/item"',
        ),
        GridFieldText(
            "operationplan__location",
            title=_("location"),
            editable=False,
            formatter="detail",
            extra='"role":"input/location"',
        ),
        GridFieldText(
            "operationplan__operation__name",
            title=_("operation"),
            editable=False,
            formatter="detail",
            extra='"role":"input/operation"',
        ),
        GridFieldText(
            "operationplan__batch",
            title=_("batch"),
            editable=False,
            field_name="operationplan__batch",
            initially_hidden=True,
        ),
        GridFieldText(
            "operationplan__operation__description",
            title=format_lazy("{} - {}", _("operation"), _("description")),
            editable=False,
            initially_hidden=True,
        ),
        GridFieldText(
            "operationplan__operation__category",
            title=format_lazy("{} - {}", _("operation"), _("category")),
            editable=False,
            initially_hidden=True,
        ),
        GridFieldText(
            "operationplan__operation__subcategory",
            title=format_lazy("{} - {}", _("operation"), _("subcategory")),
            editable=False,
            initially_hidden=True,
        ),
        GridFieldText(
            "operationplan__operation__type",
            title=format_lazy("{} - {}", _("operation"), _("type")),
            initially_hidden=True,
        ),
        GridFieldDuration(
            "operationplan__operation__duration",
            title=format_lazy("{} - {}", _("operation"), _("duration")),
            initially_hidden=True,
        ),
        GridFieldDuration(
            "operationplan__operation__duration_per",
            title=format_lazy("{} - {}", _("operation"), _("duration per unit")),
            initially_hidden=True,
        ),
        GridFieldDuration(
            "operationplan__operation__fence",
            title=format_lazy("{} - {}", _("operation"), _("release fence")),
            initially_hidden=True,
        ),
        GridFieldDuration(
            "operationplan__operation__posttime",
            title=format_lazy("{} - {}", _("operation"), _("post-op time")),
            initially_hidden=True,
        ),
        GridFieldNumber(
            "operationplan__operation__sizeminimum",
            title=format_lazy("{} - {}", _("operation"), _("size minimum")),
            initially_hidden=True,
        ),
        GridFieldNumber(
            "operationplan__operation__sizemultiple",
            title=format_lazy("{} - {}", _("operation"), _("size multiple")),
            initially_hidden=True,
        ),
        GridFieldNumber(
            "operationplan__operation__sizemaximum",
            title=format_lazy("{} - {}", _("operation"), _("size maximum")),
            initially_hidden=True,
        ),
        GridFieldInteger(
            "operationplan__operation__priority",
            title=format_lazy("{} - {}", _("operation"), _("priority")),
            initially_hidden=True,
        ),
        GridFieldDateTime(
            "operationplan__operation__effective_start",
            title=format_lazy("{} - {}", _("operation"), _("effective start")),
            initially_hidden=True,
        ),
        GridFieldDateTime(
            "operationplan__operation__effective_end",
            title=format_lazy("{} - {}", _("operation"), _("effective end")),
            initially_hidden=True,
        ),
        GridFieldCurrency(
            "operationplan__operation__cost",
            title=format_lazy("{} - {}", _("operation"), _("cost")),
            initially_hidden=True,
        ),
        GridFieldText(
            "operationplan__operation__search",
            title=format_lazy("{} - {}", _("operation"), _("search mode")),
            initially_hidden=True,
        ),
        GridFieldText(
            "operationplan__operation__source",
            title=format_lazy("{} - {}", _("operation"), _("source")),
            initially_hidden=True,
        ),
        GridFieldLastModified(
            "operationplan__operation__lastmodified",
            title=format_lazy("{} - {}", _("operation"), _("last modified")),
            initially_hidden=True,
        ),
        GridFieldDateTime(
            "operationplan__startdate",
            title=_("start date"),
            editable=False,
            extra='"formatoptions":{"srcformat":"Y-m-d H:i:s","newformat":"Y-m-d H:i:s", "defaultValue":""}, "summaryType":"min"',
        ),
        GridFieldDateTime(
            "operationplan__enddate",
            title=_("end date"),
            editable=False,
            extra='"formatoptions":{"srcformat":"Y-m-d H:i:s","newformat":"Y-m-d H:i:s", "defaultValue":""}, "summaryType":"max"',
        ),
        GridFieldDuration(
            "opplan_duration",
            title=_("duration"),
            editable=False,
            extra='"formatoptions":{"defaultValue":""}, "summaryType":"sum"',
        ),
        GridFieldDuration(
            "opplan_net_duration",
            title=_("net duration"),
            editable=False,
            extra='"formatoptions":{"defaultValue":""}, "summaryType":"sum"',
        ),
        GridFieldNumber(
            "operationplan__quantity",
            title=_("quantity"),
            editable=False,
            extra='"formatoptions":{"defaultValue":""}, "summaryType":"sum"',
        ),
        GridFieldText("operationplan__status", title=_("status"), editable=False),
        GridFieldNumber(
            "operationplan__criticality",
            title=_("criticality"),
            editable=False,
            extra='"formatoptions":{"defaultValue":""}, "summaryType":"min"',
        ),
        GridFieldDuration(
            "delay",
            title=_("delay"),
            field_name="operationplan__delay",
            editable=False,
            extra='"formatoptions":{"defaultValue":""}, "summaryType":"max"',
        ),
        GridFieldText(
            "demands",
            title=_("demands"),
            formatter="demanddetail",
            extra='"role":"input/demand"',
            width=300,
            editable=False,
            sortable=False,
        ),
        GridFieldText(
            "operationplan__type",
            title=_("type"),
            field_name="operationplan__type",
            editable=False,
        ),
        GridFieldNumber(
            "quantity",
            title=_("load quantity"),
            extra='"formatoptions":{"defaultValue":""}, "summaryType":"sum"',
        ),
        GridFieldText("setup", title=_("setup"), editable=False, initially_hidden=True),
        GridFieldDateTime(
            "setup_end",
            title=_("setup end date"),
            editable=False,
            initially_hidden=True,
        ),
        GridFieldDuration(
            "setup_duration",
            title=_("setup duration"),
            editable=False,
            initially_hidden=True,
            search=False,
        ),
        GridFieldBool(
            "feasible",
            title=_("feasible"),
            editable=False,
            initially_hidden=True,
            search=False,
        ),
        # Optional fields referencing the item
        GridFieldText(
            "operationplan__item__type",
            title=format_lazy("{} - {}", _("item"), _("type")),
            initially_hidden=True,
            editable=False,
        ),
        GridFieldText(
            "operationplan__item__description",
            initially_hidden=True,
            editable=False,
            title=format_lazy("{} - {}", _("item"), _("description")),
        ),
        GridFieldText(
            "operationplan__item__category",
            initially_hidden=True,
            editable=False,
            title=format_lazy("{} - {}", _("item"), _("category")),
        ),
        GridFieldText(
            "operationplan__item__subcategory",
            initially_hidden=True,
            editable=False,
            title=format_lazy("{} - {}", _("item"), _("subcategory")),
        ),
        GridFieldCurrency(
            "operationplan__item__cost",
            title=format_lazy("{} - {}", _("item"), _("cost")),
            initially_hidden=True,
            editable=False,
        ),
        GridFieldNumber(
            "operationplan__item__volume",
            title=format_lazy("{} - {}", _("item"), _("volume")),
            initially_hidden=True,
            editable=False,
        ),
        GridFieldNumber(
            "operationplan__item__weight",
            title=format_lazy("{} - {}", _("item"), _("weight")),
            initially_hidden=True,
            editable=False,
        ),
        GridFieldText(
            "operationplan__item__owner",
            initially_hidden=True,
            editable=False,
            title=format_lazy("{} - {}", _("item"), _("owner")),
            field_name="operationplan__item__owner__name",
        ),
        GridFieldText(
            "operationplan__item__source",
            initially_hidden=True,
            editable=False,
            title=format_lazy("{} - {}", _("item"), _("source")),
        ),
        GridFieldLastModified(
            "operationplan__item__lastmodified",
            initially_hidden=True,
            editable=False,
            title=format_lazy("{} - {}", _("item"), _("last modified")),
        ),
        # Optional fields referencing the operation location
        GridFieldText(
            "operationplan__operation__location__description",
            initially_hidden=True,
            editable=False,
            title=format_lazy("{} - {}", _("location"), _("description")),
        ),
        GridFieldText(
            "operationplan__operation__location__category",
            title=format_lazy("{} - {}", _("location"), _("category")),
            initially_hidden=True,
            editable=False,
        ),
        GridFieldText(
            "operationplan__operation__location__subcategory",
            title=format_lazy("{} - {}", _("location"), _("subcategory")),
            initially_hidden=True,
            editable=False,
        ),
        GridFieldText(
            "operationplan__operation__location__available",
            editable=False,
            title=format_lazy("{} - {}", _("location"), _("available")),
            initially_hidden=True,
            field_name="operationplan__operation__location__available__name",
            formatter="detail",
            extra='"role":"input/calendar"',
        ),
        GridFieldText(
            "operationplan__operation__location__owner",
            initially_hidden=True,
            title=format_lazy("{} - {}", _("location"), _("owner")),
            field_name="operationplan__operation__location__owner__name",
            formatter="detail",
            extra='"role":"input/location"',
            editable=False,
        ),
        GridFieldText(
            "operationplan__operation__location__source",
            initially_hidden=True,
            editable=False,
            title=format_lazy("{} - {}", _("location"), _("source")),
        ),
        GridFieldLastModified(
            "operationplan__operation__location__lastmodified",
            initially_hidden=True,
            editable=False,
            title=format_lazy("{} - {}", _("location"), _("last modified")),
        ),
        # Optional fields referencing the resource
        GridFieldText(
            "resource__description",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("description")),
        ),
        GridFieldText(
            "resource__category",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("category")),
        ),
        GridFieldText(
            "resource__subcategory",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("subcategory")),
        ),
        GridFieldText(
            "resource__type",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("type")),
        ),
        GridFieldBool(
            "resource__constrained",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("constrained")),
        ),
        GridFieldNumber(
            "resource__maximum",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("maximum")),
        ),
        GridFieldText(
            "resource__maximum_calendar",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("maximum calendar")),
            field_name="resource__maximum_calendar__name",
            formatter="detail",
            extra='"role":"input/calendar"',
        ),
        GridFieldCurrency(
            "resource__cost",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("cost")),
        ),
        GridFieldDuration(
            "resource__maxearly",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("maxearly")),
        ),
        GridFieldText(
            "resource__setupmatrix",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("setupmatrix")),
            field_name="resource__setupmatrix__name",
            formatter="detail",
            extra='"role":"input/setupmatrix"',
        ),
        GridFieldText(
            "resource__setup",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("setup")),
        ),
        GridFieldText(
            "resource_location",
            editable=False,
            initially_hidden=True,
            title=format_lazy("{} - {}", _("resource"), _("location")),
            field_name="resource__location__name",
            formatter="detail",
            extra='"role":"input/location"',
        ),
        # Optional fields referencing the resource location
        GridFieldText(
            "resource__location__description",
            initially_hidden=True,
            editable=False,
            title=format_lazy(
                "{} - {} - {}", _("resource"), _("location"), _("description")
            ),
        ),
        GridFieldText(
            "resource__location__category",
            initially_hidden=True,
            editable=False,
            title=format_lazy(
                "{} - {} - {}", _("resource"), _("location"), _("category")
            ),
        ),
        GridFieldText(
            "resource__location__subcategory",
            initially_hidden=True,
            editable=False,
            title=format_lazy(
                "{} - {} - {}", _("resource"), _("location"), _("subcategory")
            ),
        ),
        GridFieldText(
            "resource__location__available",
            initially_hidden=True,
            editable=False,
            title=format_lazy(
                "{} - {} - {}", _("resource"), _("location"), _("available")
            ),
            field_name="resource__location__available__name",
            formatter="detail",
            extra='"role":"input/calendar"',
        ),
        GridFieldText(
            "resource__location__owner",
            extra='"role":"input/location"',
            editable=False,
            title=format_lazy("{} - {} - {}", _("resource"), _("location"), _("owner")),
            initially_hidden=True,
            field_name="resource__location__owner__name",
            formatter="detail",
        ),
        GridFieldText(
            "resource__location__source",
            initially_hidden=True,
            editable=False,
            title=format_lazy(
                "{} - {} - {}", _("resource"), _("location"), _("source")
            ),
        ),
        # Status field currently not used
        # GridFieldChoice('status', title=_('load status'), choices=OperationPlanResource.OPRstatus),
        GridFieldLastModified("lastmodified", initially_hidden=True),
    )
