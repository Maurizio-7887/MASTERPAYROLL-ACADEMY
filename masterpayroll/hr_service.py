"""Calcolo di giorni/ore lavorabili e assenze dal calendario (resource + hr_holidays).

Riproduce ciò che in Odoo fanno ``employee._get_work_days_data_batch`` e
``employee.list_leaves`` usati da ``hr.payslip.get_worked_day_lines``.
"""
from datetime import timedelta

from .models import Leave, ResourceCalendarLeave

WEEKDAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def daterange(d1, d2):
    d = d1
    while d <= d2:
        yield d
        d += timedelta(days=1)


def attendance_intervals(calendar, day):
    if not calendar:
        return []
    return [(a.hour_from, a.hour_to) for a in calendar.attendance_ids if a.dayofweek == day.weekday()]


def day_work_hours(calendar, day):
    return sum(t - f for f, t in attendance_intervals(calendar, day))


def overlap_hours(intervals, h_from, h_to):
    return sum(max(0.0, min(t, h_to) - max(f, h_from)) for f, t in intervals)


def work_days_data(calendar, day_from, day_to):
    """Giorni e ore previsti dal calendario (festività comprese, come compute_leaves=False)."""
    days = hours = 0.0
    for d in daterange(day_from, day_to):
        h = day_work_hours(calendar, d)
        if h > 0:
            days += 1
            hours += h
    return {"days": days, "hours": round(hours, 2)}


def list_leaves(employee, calendar, day_from, day_to):
    """Elenco (giorno, ore, tipo) delle assenze nel periodo.

    tipo = LeaveType per le assenze approvate, None per le festività (Global Leaves).
    """
    out = []
    if not calendar:
        return out
    globals_ = {gl.date: gl for gl in ResourceCalendarLeave.query.filter(
        ResourceCalendarLeave.workspace_id == employee.workspace_id,
        ResourceCalendarLeave.date >= day_from, ResourceCalendarLeave.date <= day_to)
        if gl.calendar_id in (None, calendar.id)}
    leaves = Leave.query.filter(Leave.employee_id == employee.id, Leave.state == "validate",
                                Leave.date_from <= day_to, Leave.date_to >= day_from).all()
    for d in daterange(day_from, day_to):
        intervals = attendance_intervals(calendar, d)
        h_day = sum(t - f for f, t in intervals)
        if h_day <= 0:
            continue
        if d in globals_:
            out.append((d, h_day, None))
            continue
        for lv in leaves:
            if not (lv.date_from <= d <= lv.date_to):
                continue
            if lv.request_unit_hours and lv.hour_from is not None and lv.hour_to is not None:
                h = overlap_hours(intervals, lv.hour_from, lv.hour_to)
            else:
                h = h_day
            if h > 0:
                out.append((d, h, lv.holiday_status))
    return out


def leave_duration(leave):
    """Giorni e ore di un'assenza secondo il calendario del dipendente (per la lista assenze)."""
    cal = leave.employee.resource_calendar if leave.employee else None
    days = hours = 0.0
    for d in daterange(leave.date_from, leave.date_to):
        intervals = attendance_intervals(cal, d)
        h_day = sum(t - f for f, t in intervals)
        if h_day <= 0:
            continue
        if leave.request_unit_hours and leave.hour_from is not None and leave.hour_to is not None:
            h = overlap_hours(intervals, leave.hour_from, leave.hour_to)
        else:
            h = h_day
        hours += h
        days += h / h_day
    return round(days, 2), round(hours, 2)


def italian_holidays(year):
    """Festività nazionali italiane (Pasqua con l'algoritmo di Gauss/Meeus)."""
    from datetime import date
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = ((h + m - 7 * n + 114) % 31) + 1
    pasqua = date(year, month, day)
    extra = []
    if year >= 2026:  # festa nazionale ripristinata dal 2026 (verificare in aula)
        extra.append((date(year, 10, 4), "San Francesco d'Assisi e Santa Caterina da Siena"))
    return extra + [
        (date(year, 1, 1), "Capodanno"), (date(year, 1, 6), "Epifania"),
        (pasqua, "Pasqua"), (pasqua + timedelta(days=1), "Lunedì dell'Angelo"),
        (date(year, 4, 25), "Festa della Liberazione"), (date(year, 5, 1), "Festa del Lavoro"),
        (date(year, 6, 2), "Festa della Repubblica"), (date(year, 8, 15), "Ferragosto"),
        (date(year, 11, 1), "Ognissanti"), (date(year, 12, 8), "Immacolata Concezione"),
        (date(year, 12, 25), "Natale"), (date(year, 12, 26), "Santo Stefano"),
    ]


# ---------------------------------------------------------------------------
# Malattia: indennità INPS per giorni di calendario dell'evento
# ---------------------------------------------------------------------------
def malattia_periodo(employee, contract, day_from, day_to, perc1=50.0, perc2=66.67):
    """Giorni di malattia del periodo divisi per fascia, contando il giorno dell'EVENTO (dal 1° giorno di malattia,
    anche se è iniziato il mese prima): 1-3 carenza (pagata dall'azienda), 4-20 INPS al perc1%, 21-180 al perc2%.

    Semplificazione didattica: retribuzione media giornaliera = retribuzione mensile / 30 per tutti
    (per gli operai l'INPS usa /26 e non indennizza le domeniche)."""
    from .models import LeaveType
    out = {"carenza": 0, "gg50": 0, "gg67": 0, "rmg": 0.0, "importo": 0.0, "eventi": []}
    if not contract:
        return out
    rmg = round(contract.retribuzione_mensile / 30, 2)
    out["rmg"] = rmg
    leaves = (Leave.query.join(LeaveType, Leave.holiday_status_id == LeaveType.id)
              .filter(Leave.employee_id == employee.id, Leave.state == "validate", LeaveType.code == "MAL",
                      Leave.date_from <= day_to, Leave.date_to >= day_from).order_by(Leave.date_from).all())
    for lv in leaves:
        ev = {"dal": lv.date_from, "al": lv.date_to, "carenza": 0, "gg50": 0, "gg67": 0}
        for d in daterange(max(lv.date_from, day_from), min(lv.date_to, day_to)):
            n = (d - lv.date_from).days + 1
            if n <= 3:
                ev["carenza"] += 1
            elif n <= 20:
                ev["gg50"] += 1
            elif n <= 180:
                ev["gg67"] += 1
        for k in ("carenza", "gg50", "gg67"):
            out[k] += ev[k]
        out["eventi"].append(ev)
    out["importo"] = round(out["gg50"] * rmg * perc1 / 100 + out["gg67"] * rmg * perc2 / 100, 2)
    return out


# ---------------------------------------------------------------------------
# Ferie e permessi: maturato, goduto, residuo
# ---------------------------------------------------------------------------
def mesi_maturati(contract, anno, fino):
    """Mesi dell'anno che maturano ferie e permessi (mese con almeno 15 giorni di rapporto), fino alla data."""
    import calendar as _c
    from datetime import date
    n = 0
    for m in range(1, fino.month + 1 if fino.year == anno else 13):
        last = _c.monthrange(anno, m)[1]
        start = max(date(anno, m, 1), contract.date_start)
        end = min(date(anno, m, last), contract.date_end or date(anno, m, last), fino)
        if end >= start and (end - start).days + 1 >= 15:
            n += 1
    return n


def contatori_ferie(employee, anno, fino, ore_ferie_anno=160.0, ore_rol_anno=104.0):
    """Ore di ferie e di permessi (ROL + ex festività) maturate, godute e residue nell'anno fino alla data.

    Maturazione in dodicesimi per i mesi di rapporto, riproporzionata al part-time; il goduto si legge dalle
    assenze approvate FERIE e ROL fino alla data."""
    from datetime import date
    from .models import LeaveType
    contracts = [c for c in employee.contract_ids if c.state in ("open", "close")
                 and c.date_start <= fino and (c.date_end is None or c.date_end >= date(anno, 1, 1))]
    mat_f = mat_r = 0.0
    for c in contracts:
        mesi = mesi_maturati(c, anno, fino)
        pt = (c.part_time or 100) / 100
        mat_f += ore_ferie_anno * pt * mesi / 12
        mat_r += ore_rol_anno * pt * mesi / 12
    god = {"FERIE": 0.0, "ROL": 0.0}
    leaves = (Leave.query.join(LeaveType, Leave.holiday_status_id == LeaveType.id)
              .filter(Leave.employee_id == employee.id, Leave.state == "validate", LeaveType.code.in_(("FERIE", "ROL")),
                      Leave.date_from <= fino, Leave.date_to >= date(anno, 1, 1)).all())
    cal = employee.resource_calendar
    for lv in leaves:
        for d in daterange(max(lv.date_from, date(anno, 1, 1)), min(lv.date_to, fino)):
            intervals = attendance_intervals(cal, d)
            h_day = sum(t - f for f, t in intervals)
            if h_day <= 0:
                continue
            h = overlap_hours(intervals, lv.hour_from, lv.hour_to) if (
                lv.request_unit_hours and lv.hour_from is not None and lv.hour_to is not None) else h_day
            god[lv.holiday_status.code] += h
    r = lambda x: round(x, 2)  # noqa: E731
    return {"ferie_maturate": r(mat_f), "ferie_godute": r(god["FERIE"]), "ferie_residue": r(mat_f - god["FERIE"]),
            "rol_maturati": r(mat_r), "rol_goduti": r(god["ROL"]), "rol_residui": r(mat_r - god["ROL"]),
            "residuo_totale": r(mat_f - god["FERIE"] + mat_r - god["ROL"])}
