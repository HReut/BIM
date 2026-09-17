"""
QA extraction script for the Model Health Board.

Runs inside pyRevit against a live, open Revit document and merges one run
into this model's history inside sample-data/health-history.json, matching
schema/health-report.schema.json (project -> disciplines[] -> models[] ->
history[]). One deployment of this script targets exactly one model, so
DISCIPLINE_ID / MODEL_ID and PROJECT_CONFIG below must be set per model
before wiring it into that model's pyRevit button.

Not every check in CHECK_DEFINITIONS has a working implementation yet:
    - acc_access / cloud_model_exists / all_models_in_cloud need the
      ACC/Forma API (no license to verify against) — skipped entirely.
    - coordinates_acquired / copy_monitor_levels / levels_match /
      copy_monitor_grids / grids_match / shared_coordinates /
      base_point_integrity need either the linked reference model opened
      (`RevitLinkInstance.GetLinkDocument()`) or a persisted baseline to
      compare against — see the stub functions below for what each needs.
      Left as stubs (return None) rather than guessed at, since none of
      this has been run against a live Revit session.

Environment:
    - pyRevit, CPython 3 engine (`#!python3` below). If your pyRevit build only
      ships the IronPython 2.7 engine, port the f-strings and `pathlib` usage
      before use.
    - Verify pyRevit's Revit 2027 support against the pyRevit release notes
      before wiring this into a production button — that compatibility can't
      be confirmed from here.
    - units_consistency uses the SpecTypeId/UnitTypeId API (Revit 2021+);
      older API versions use DisplayUnitType instead.

Wire this into a pyRevit extension as a button's script.py, or run it once
via pyRevit's "Run Script" / RevitPythonShell for testing.
"""
#!python3
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from pyrevit import revit, DB, script

output = script.get_output()
doc = revit.doc

# --- Identity: edit these per model deployment. DISCIPLINE_ID and MODEL_ID
# are stable keys in the JSON tree — changing them after the fact orphans
# that model's existing history instead of continuing it. ---
PROJECT_NAME = "Sample Tower"
PROJECT_CODE = "ST"
DISCIPLINE_ID = "str"
DISCIPLINE_LABEL = "קונסטרוקציה"
MODEL_ID = "str-super"
MODEL_LABEL = "STR - Superstructure"

# --- Project config: the BEP rules config-driven checks are evaluated
# against. In the SaaS platform this becomes a per-project settings page a
# BIM Manager edits (see schema/health-report.schema.json's project.config);
# today it's edited by hand here, once per deployed project. ---
PROJECT_CONFIG = {
    "referenceDiscipline": "arc",
    "modelNamingPattern": r"^%s-[A-Z]+-[A-Z0-9]+\.rvt$" % re.escape(PROJECT_CODE),
    "sheetNumberPattern": r"^%s-[A-Z]+-[A-Z]-\d{3}$" % re.escape(PROJECT_CODE),
    "expectedWorksetPatterns": [
        r"^01_Shared Levels and Grids$",
        r"^02_.+_Model$",
        r"^03_Links$",
    ],
    "linkWorksetPattern": r"^03_Links$",
    "expectedLinksByDiscipline": {
        "arc": [], "str": ["arc"], "hvac": ["arc", "str"], "elec": ["arc", "str"],
        "plumb": ["arc", "str"], "land": ["arc"],
    },
    "expectedLengthUnit": "millimeters",
    # Rough per-model completion target for modeling_progress_pct — replace
    # with a real BEP milestone count once one exists; this is a placeholder.
    "modelingProgressTargetElements": 8000,
}

# Must mirror schema/health-report.schema.json + sample-data/health-history.json
# so extraction output and dashboard scoring never drift apart.
CHECK_DEFINITIONS = [
    # --- Coordination & Setup ---
    {"id": "acc_access", "label": "גישה למתכנן ב-ACC/FORMA", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "coming_soon"},
    {"id": "cloud_model_exists", "label": "המודל קיים בענן (ACC/FORMA)", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "coming_soon"},
    {"id": "all_models_in_cloud", "label": "כלל מודלי הדיספלינה הוקמו בענן", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "coming_soon"},
    {"id": "naming_convention_model", "label": "שם המודל עומד בתקן הקידוד", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1},
    {"id": "coordinates_acquired", "label": "נרכשו קואורדינטות ממודל הייחוס", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1, "excludeReference": True},
    {"id": "copy_monitor_levels", "label": "בוצע Copy/Monitor למפלסים", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1, "excludeReference": True},
    {"id": "levels_match", "label": "מפלסים זהים (כמות/שם/גובה) למודל הייחוס", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1, "excludeReference": True},
    {"id": "copy_monitor_grids", "label": "בוצע Copy/Monitor לצירים", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1, "excludeReference": True},
    {"id": "grids_match", "label": "צירים זהים (כמות/שם) למודל הייחוס", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1, "excludeReference": True},
    {"id": "worksets_per_bep", "label": "Worksets הוקמו לפי ה-BEP", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1},
    {"id": "all_links_loaded", "label": "כל מודלי הדיספלינות הרלוונטיות טעונים כ-Links", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1},
    {"id": "links_correct_workset", "label": "ה-Links ממוקמים ב-Workset הנכון", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1},
    {"id": "shared_coordinates", "label": "המודל במערכת הקואורדינטות המשותפת (Shared Site)", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1},
    {"id": "base_point_integrity", "label": "Project Base Point / Survey Point לא הוזזו", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1},
    {"id": "units_consistency", "label": "יחידות המודל תואמות לתקן הפרויקט", "category": "קואורדינציה והקמה",
     "categoryGroup": "coordination", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1},
    # --- Modeling progress / hygiene ---
    {"id": "modeling_progress_pct", "label": "היקף התקדמות מידול", "category": "התקדמות מידול",
     "categoryGroup": "modeling", "unit": "%", "higherIsBetter": True, "status": "available",
     "goodMin": 40, "warnMin": 15, "critMin": 1},
    {"id": "duplicate_elements", "label": "אלמנטים כפולים / חופפים", "category": "התקדמות מידול",
     "categoryGroup": "modeling", "unit": "count", "higherIsBetter": False, "status": "available",
     "goodMax": 0, "warnMax": 3, "critMax": 10},
    {"id": "sync_recency_days", "label": "ימים מאז Sync אחרון", "category": "התקדמות מידול",
     "categoryGroup": "modeling", "unit": "days", "higherIsBetter": False, "status": "available",
     "goodMax": 1, "warnMax": 3, "critMax": 7},
    {"id": "worksharing_display_name", "label": "Worksharing Display Name מוגדר", "category": "התקדמות מידול",
     "categoryGroup": "modeling", "unit": "bool", "higherIsBetter": True, "status": "available",
     "goodMin": 1, "warnMin": 1, "critMin": 1},
    {"id": "warnings", "label": "Warnings", "category": "Model Cleanliness", "categoryGroup": "modeling",
     "unit": "count", "higherIsBetter": False, "status": "available", "goodMax": 30, "warnMax": 80, "critMax": 160},
    {"id": "workset1_elements", "label": "Elements on Workset1/Default", "category": "Worksharing", "categoryGroup": "modeling",
     "unit": "count", "higherIsBetter": False, "status": "available", "goodMax": 0, "warnMax": 15, "critMax": 40},
    {"id": "unplaced_rooms", "label": "Unplaced / Unenclosed Rooms", "category": "Rooms & Spaces", "categoryGroup": "modeling",
     "unit": "count", "higherIsBetter": False, "status": "available", "goodMax": 0, "warnMax": 5, "critMax": 15},
    {"id": "duplicate_types", "label": "Duplicate-Named Family Types", "category": "Families", "categoryGroup": "modeling",
     "unit": "count", "higherIsBetter": False, "status": "available", "goodMax": 0, "warnMax": 3, "critMax": 10},
    {"id": "view_template_coverage", "label": "View Template Coverage", "category": "Views & Sheets", "categoryGroup": "modeling",
     "unit": "%", "higherIsBetter": True, "status": "available", "goodMin": 90, "warnMin": 70, "critMin": 40},
    {"id": "views_not_on_sheets", "label": "Views Not Placed on Sheets", "category": "Views & Sheets", "categoryGroup": "modeling",
     "unit": "count", "higherIsBetter": False, "status": "available", "goodMax": 5, "warnMax": 20, "critMax": 50},
    {"id": "model_groups", "label": "Model Groups", "category": "Model Cleanliness", "categoryGroup": "modeling",
     "unit": "count", "higherIsBetter": False, "status": "available", "goodMax": 5, "warnMax": 15, "critMax": 30},
    # --- Documentation ---
    {"id": "sheet_naming_compliance", "label": "גיליונות עומדים בתקן הקידוד", "category": "תיעוד",
     "categoryGroup": "documentation", "unit": "%", "higherIsBetter": True, "status": "available",
     "goodMin": 95, "warnMin": 80, "critMin": 50},
    # --- Performance ---
    {"id": "file_size_mb", "label": "Central File Size", "category": "Performance", "categoryGroup": "performance",
     "unit": "MB", "higherIsBetter": False, "status": "available", "goodMax": 250, "warnMax": 400, "critMax": 600},
]


# ============================== Local checks ================================
# Solid, well-understood Revit API — implemented for real.

def count_warnings():
    return len(doc.GetWarnings())


def count_workset1_elements():
    if not doc.IsWorkshared:
        return 0
    worksets = DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)
    default_ids = {w.Id for w in worksets if w.Name in ("Workset1", "Shared Levels and Grids")}
    if not default_ids:
        return 0
    elements = DB.FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()
    return sum(1 for el in elements if el.WorksetId in default_ids)


def count_unplaced_rooms():
    rooms = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms) \
        .WhereElementIsNotElementType().ToElements()
    return sum(1 for r in rooms if r.Area <= 0 or r.Location is None)


def count_duplicate_types():
    symbols = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).ToElements()
    names_by_category = {}
    for s in symbols:
        cat = s.Category.Name if s.Category else "Uncategorized"
        names_by_category.setdefault(cat, {}).setdefault(s.Name, set()).add(s.Family.Name)
    duplicates = 0
    for by_name in names_by_category.values():
        for families in by_name.values():
            if len(families) > 1:
                duplicates += 1
    return duplicates


def _eligible_views():
    views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
    return [v for v in views if not v.IsTemplate and not v.ViewType == DB.ViewType.Schedule
            and not v.ViewType == DB.ViewType.SystemBrowser]


def view_template_coverage_pct():
    views = _eligible_views()
    if not views:
        return 100.0
    with_template = sum(1 for v in views if v.ViewTemplateId != DB.ElementId.InvalidElementId)
    return round(100.0 * with_template / len(views), 1)


def count_views_not_on_sheets():
    viewports = DB.FilteredElementCollector(doc).OfClass(DB.Viewport).ToElements()
    on_sheet_ids = {vp.ViewId for vp in viewports}
    views = _eligible_views()
    return sum(1 for v in views if v.Id not in on_sheet_ids)


def count_model_groups():
    return len(DB.FilteredElementCollector(doc).OfClass(DB.GroupType).ToElements())


def file_size_mb():
    path = doc.PathName
    if not path or not os.path.exists(path):
        return 0.0
    return round(os.path.getsize(path) / (1024 * 1024), 1)


def naming_convention_model():
    name = Path(doc.PathName).name if doc.PathName else doc.Title
    return 1 if re.match(PROJECT_CONFIG["modelNamingPattern"], name) else 0


def worksets_per_bep():
    if not doc.IsWorkshared:
        return 0
    names = [w.Name for w in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)]
    for pattern in PROJECT_CONFIG["expectedWorksetPatterns"]:
        if not any(re.match(pattern, n) for n in names):
            return 0
    return 1


def sheet_naming_compliance():
    sheets = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements()
    if not sheets:
        return 100.0
    pattern = PROJECT_CONFIG["sheetNumberPattern"]
    compliant = sum(1 for s in sheets if re.match(pattern, s.SheetNumber or ""))
    return round(100.0 * compliant / len(sheets), 1)


# Categories prone to accidental double-placement (copy/paste, undo mishaps).
# Bounded to these + a element cap so this stays a quick heuristic, not an
# exhaustive clash check — pair it with a real coordination tool for that.
_DUPLICATE_CHECK_CATEGORIES = [
    DB.BuiltInCategory.OST_Doors, DB.BuiltInCategory.OST_Windows,
    DB.BuiltInCategory.OST_Furniture, DB.BuiltInCategory.OST_StructuralFraming,
    DB.BuiltInCategory.OST_StructuralColumns,
]
_DUPLICATE_CHECK_ELEMENT_CAP = 3000


def count_duplicate_elements():
    seen = {}
    duplicates = 0
    checked = 0
    for bic in _DUPLICATE_CHECK_CATEGORIES:
        elements = DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements()
        for el in elements:
            checked += 1
            if checked > _DUPLICATE_CHECK_ELEMENT_CAP:
                return duplicates
            bbox = el.get_BoundingBox(None)
            if bbox is None:
                continue
            center = bbox.Min + (bbox.Max - bbox.Min) * 0.5
            # Round to 10mm (~0.03ft) so near-identical placements collide
            # into the same bucket without needing true geometric overlap.
            key = (el.Category.Id.IntegerValue, round(center.X, 2), round(center.Y, 2), round(center.Z, 2))
            if key in seen:
                duplicates += 1
            else:
                seen[key] = el.Id
    return duplicates


def modeling_progress_pct():
    elements = DB.FilteredElementCollector(doc).WhereElementIsNotElementType() \
        .WhereElementIsViewIndependent().ToElements()
    target = PROJECT_CONFIG["modelingProgressTargetElements"]
    return round(min(100.0, 100.0 * len(elements) / target), 1)


def sync_recency_days():
    # Best-effort proxy: file modified time on the central/local path. Revit
    # doesn't expose "last successful Sync with Central" timestamp directly
    # via the public API, so this can undercount if the model was edited
    # locally without a sync — treat it as an approximation.
    path = doc.PathName
    if not path or not os.path.exists(path):
        return 0
    age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))
    return max(0, age.days)


def worksharing_display_name():
    # Presence check only — confirms *a* worksharing username is configured,
    # not that it matches a "First Last" naming convention. Tighten with a
    # regex against PROJECT_CONFIG if the BEP defines one.
    username = getattr(doc.Application, "Username", "") or ""
    return 1 if username.strip() else 0


def units_consistency():
    try:
        length_unit = doc.GetUnits().GetFormatOptions(DB.SpecTypeId.Length).GetUnitTypeId()
    except AttributeError:
        # Pre-2021 API fallback.
        length_unit = doc.GetUnits().GetFormatOptions(DB.UnitType.UT_Length).DisplayUnits
    expected = PROJECT_CONFIG["expectedLengthUnit"]
    return 1 if expected in str(length_unit).lower() else 0


def _loaded_link_names():
    link_types = DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType).ToElements()
    return [lt.Name for lt in link_types if lt.GetLinkedFileStatus() == DB.LinkedFileStatus.Loaded]


def all_links_loaded():
    expected_disciplines = PROJECT_CONFIG["expectedLinksByDiscipline"].get(DISCIPLINE_ID, [])
    if not expected_disciplines:
        return 1
    loaded_names = [n.upper() for n in _loaded_link_names()]
    # Heuristic: match by the expected discipline's code appearing in the
    # linked file's name (relies on naming_convention_model being enforced
    # project-wide — without that, this can't reliably identify which link
    # is which discipline).
    for disc_id in expected_disciplines:
        if not any(disc_id.upper() in name for name in loaded_names):
            return 0
    return 1


def links_correct_workset():
    if not doc.IsWorkshared:
        return 1
    instances = DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance).ToElements()
    if not instances:
        return 1
    pattern = PROJECT_CONFIG["linkWorksetPattern"]
    worksets = {w.Id: w.Name for w in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)}
    for inst in instances:
        workset_name = worksets.get(inst.WorksetId, "")
        if not re.match(pattern, workset_name):
            return 0
    return 1


# ============================ Stubs — not implemented ========================
# Each of these needs something this script can't safely guess at without a
# live Revit session to verify against: either the linked reference model
# opened via RevitLinkInstance.GetLinkDocument() (only available when the
# link is loaded) and its Level/Grid collections compared to this doc's, or
# a persisted baseline from a previous run (base_point_integrity has no
# "correct" value without one — the first successful run should record it).
# Returning None here means run_all_checks() omits the key entirely, same
# as an ACC-dependent check — the dashboard renders no card rather than a
# guessed one.

def coordinates_acquired():
    """Needs: RevitLinkType.GetTransform()/AttachmentType compared against
    the reference model's shared coordinates, or GetLinkDocument() + a
    documented "acquired coordinates" flag — not verified against a live
    Revit session yet."""
    return None


def copy_monitor_levels():
    """Needs: DB.ElementId.GetMonitoredLinkElementId() (or the current
    Revit 2027 equivalent — API name to confirm) on this doc's Level
    elements against the linked reference model's levels."""
    return None


def levels_match():
    """Needs: GetLinkDocument() on the reference-discipline link, then
    compare Level count/name/elevation between the two documents."""
    return None


def copy_monitor_grids():
    """Same shape as copy_monitor_levels(), for Grid elements."""
    return None


def grids_match():
    """Same shape as levels_match(), for Grid elements."""
    return None


def shared_coordinates():
    """Needs: confirming this model's ProjectLocation/SiteLocation was
    acquired from the reference model rather than left at Internal Origin —
    the exact API (ProjectPosition vs SiteLocation) needs checking against
    a live session before trusting a boolean out of it."""
    return None


def base_point_integrity():
    """Needs a persisted baseline: record BasePoint.GetProjectBasePoint(doc)
    / GetSurveyPoint(doc) position on the first successful run, then compare
    against that baseline on every later run. Nothing to compare against
    yet — wire this up once merge_run() can read back the previous run's
    raw position (not just its checks dict)."""
    return None


CHECK_FUNCTIONS = {
    "warnings": count_warnings,
    "workset1_elements": count_workset1_elements,
    "unplaced_rooms": count_unplaced_rooms,
    "duplicate_types": count_duplicate_types,
    "view_template_coverage": view_template_coverage_pct,
    "views_not_on_sheets": count_views_not_on_sheets,
    "model_groups": count_model_groups,
    "file_size_mb": file_size_mb,
    "naming_convention_model": naming_convention_model,
    "coordinates_acquired": coordinates_acquired,
    "copy_monitor_levels": copy_monitor_levels,
    "levels_match": levels_match,
    "copy_monitor_grids": copy_monitor_grids,
    "grids_match": grids_match,
    "worksets_per_bep": worksets_per_bep,
    "all_links_loaded": all_links_loaded,
    "links_correct_workset": links_correct_workset,
    "shared_coordinates": shared_coordinates,
    "base_point_integrity": base_point_integrity,
    "units_consistency": units_consistency,
    "modeling_progress_pct": modeling_progress_pct,
    "duplicate_elements": count_duplicate_elements,
    "sync_recency_days": sync_recency_days,
    "worksharing_display_name": worksharing_display_name,
    "sheet_naming_compliance": sheet_naming_compliance,
}


def score_for(check_def, value):
    if check_def["higherIsBetter"]:
        if value >= check_def["goodMin"]:
            return 100
        if value <= check_def["critMin"]:
            return 10
        if value >= check_def["warnMin"]:
            return 60 + 40 * (value - check_def["warnMin"]) / (check_def["goodMin"] - check_def["warnMin"])
        return 10 + 50 * (value - check_def["critMin"]) / (check_def["warnMin"] - check_def["critMin"])
    else:
        if value <= check_def["goodMax"]:
            return 100
        if value >= check_def["critMax"]:
            return 10
        if value <= check_def["warnMax"]:
            span = max(1, check_def["warnMax"] - check_def["goodMax"])
            return 60 + 40 * (check_def["warnMax"] - value) / span
        span = max(1, check_def["critMax"] - check_def["warnMax"])
        return 10 + 50 * (check_def["critMax"] - value) / span


def run_all_checks():
    is_reference = DISCIPLINE_ID == PROJECT_CONFIG["referenceDiscipline"]
    checks = {}
    for check_def in CHECK_DEFINITIONS:
        if check_def["status"] != "available":
            continue  # coming_soon (ACC-dependent) — nothing to compute yet
        if check_def.get("excludeReference") and is_reference:
            continue  # e.g. architecture doesn't check coordinates against itself
        fn = CHECK_FUNCTIONS[check_def["id"]]
        try:
            value = fn()
        except Exception as ex:  # a single bad check shouldn't blank the whole run
            output.print_md(f"**Warning:** check `{check_def['id']}` failed: {ex}")
            value = None
        if value is not None:  # stubs return None — omit rather than store null
            checks[check_def["id"]] = value
    return checks


def compute_health_score(checks):
    scores = []
    for check_def in CHECK_DEFINITIONS:
        value = checks.get(check_def["id"])
        if value is None:
            continue
        scores.append(score_for(check_def, value))
    return round(sum(scores) / len(scores)) if scores else 0


def build_run_entry(checks):
    now = datetime.now(timezone.utc).astimezone()
    return {
        "runId": now.isoformat(),
        "timestamp": now.isoformat(),
        "healthScore": compute_health_score(checks),
        "checks": checks,
    }


def _find(items, item_id):
    return next((item for item in items if item["id"] == item_id), None)


def merge_run(tree_path, run_entry):
    """Merge one run into this model's history inside the project-wide tree,
    creating the project/discipline/model entries the first time this model
    reports in."""
    if tree_path.exists():
        data = json.loads(tree_path.read_text(encoding="utf-8"))
    else:
        data = {
            "schemaVersion": "3.0",
            "project": {
                "name": PROJECT_NAME, "code": PROJECT_CODE,
                "config": {
                    "referenceDiscipline": PROJECT_CONFIG["referenceDiscipline"],
                    "expectedLinksByDiscipline": PROJECT_CONFIG["expectedLinksByDiscipline"],
                },
            },
            "roles": [
                {"id": "bim_manager", "label": "מנהל BIM", "scope": "project", "detail": "full"},
                {"id": "systems_coordinator", "label": "מתאם מערכות", "scope": "project", "detail": "coordination"},
                {"id": "project_manager", "label": "מנהל פרויקט", "scope": "project", "detail": "summary"},
                {"id": "designer", "label": "מתכנן", "scope": "own_discipline", "detail": "full"},
            ],
            "checkDefinitions": CHECK_DEFINITIONS,
            "disciplines": [],
        }

    disc = _find(data["disciplines"], DISCIPLINE_ID)
    if disc is None:
        disc = {"id": DISCIPLINE_ID, "label": DISCIPLINE_LABEL, "models": []}
        data["disciplines"].append(disc)

    model = _find(disc["models"], MODEL_ID)
    if model is None:
        model = {
            "id": MODEL_ID,
            "label": MODEL_LABEL,
            "modelFile": Path(doc.PathName).name if doc.PathName else doc.Title,
            "revitVersion": revit.doc.Application.VersionNumber,
            "history": [],
        }
        disc["models"].append(model)

    model["history"].append(run_entry)
    tree_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main():
    checks = run_all_checks()
    run_entry = build_run_entry(checks)

    # Point this at your synced sample-data/health-history.json (or a shared
    # network/cloud-synced path) so the dashboard picks up new runs. Every
    # model's button writes into the same file, keyed by DISCIPLINE_ID/MODEL_ID.
    tree_path = Path(__file__).resolve().parents[2] / "sample-data" / "health-history.json"
    merge_run(tree_path, run_entry)

    output.print_md(f"### {DISCIPLINE_LABEL} / {MODEL_LABEL} — health score: {run_entry['healthScore']}/100")
    for check_def in CHECK_DEFINITIONS:
        v = checks.get(check_def["id"])
        label = f"- **{check_def['label']}**: "
        label += "— (not implemented yet)" if check_def["status"] == "available" and v is None else f"{v} {check_def['unit']}"
        output.print_md(label)


if __name__ == "__main__":
    main()
