"""Native MoviePilot JSON calendar. No frontend bundle or arbitrary date queries."""
import calendar as month_calendar


def node(component, text=None, content=None, **props):
    result = {"component": component}
    if props:
        result["props"] = props
    if text is not None:
        result["text"] = text
    if content is not None:
        result["content"] = content
    return result


def _day(date, record, today):
    signed = bool(record and record["is_sign"])
    reward = bool(record and record["reward_type"] == "7")
    current = date == today
    missed = bool(record and not signed and date < today)
    style = {"minWidth": "0", "minHeight": "0", "aspectRatio": "1 / 1", "boxSizing": "border-box", "padding": "4px 1px", "borderRadius": "12px", "position": "relative",
             "display": "flex", "flexDirection": "column", "alignItems": "center", "justifyContent": "center",
             "gap": "2px", "border": "1px solid transparent", "textAlign": "center",
             "background": "rgba(var(--v-theme-on-surface),.025)", "color": "rgba(var(--v-theme-on-surface),.5)"}
    if current:
        style.update(background="rgb(var(--v-theme-primary))", color="rgb(var(--v-theme-on-primary))",
                     boxShadow="0 3px 9px rgba(var(--v-theme-primary),.2)")
    elif signed:
        style.update(background="rgba(var(--v-theme-primary),.09)", color="rgb(var(--v-theme-primary))")
    elif missed:
        style.update(background="transparent", border="1px dashed rgba(var(--v-theme-on-surface),.15)")
    detail = "未返回记录" if record is None else f"已签到，获得 {record['integral']} 积分" if signed else "漏签" if missed else "未签到" if current else "待签到"
    if reward:
        detail += "；福利积分日" + ("（已获得）" if signed else "（以当天实际签到结果为准）")
    children = [node("div", str(int(date[-2:])),
                     style={"fontSize": "clamp(14px,2vw,18px)", "lineHeight": "1.2", "fontWeight": "600"})]
    if signed:
        children.append(node("div", f"+{record['integral']}", style={"fontSize": "11px", "lineHeight": "14px", "fontWeight": "500"}))
    else:
        children.append(node("div", "—" if record is None else "漏签" if missed else "待签到" if current else "",
                             style={"fontSize": "10px", "opacity": ".7", "lineHeight": "14px", "minHeight": "14px"}))
    if reward:
        children.append(node("div", "★", style={"position": "absolute", "top": "3px", "right": "3px", "fontSize": "8px", "lineHeight": "1", "color": "rgb(var(--v-theme-on-primary))" if current else "rgb(var(--v-theme-primary))"}))
    if current:
        detail = "今日；" + detail
    return node("div", content=children, title=f"{date}：{detail}",
                **{"aria-label": f"{date}：{detail}", "aria-current": "date" if current else "false", "style": style})


def render_calendar(snapshot, last_result=None, error=""):
    last_result = last_result or {}
    cal = snapshot.get("calendar") if isinstance(snapshot, dict) else None
    months = cal.get("months", []) if isinstance(cal, dict) else []
    alerts = []
    message = error or ("最近签到失败：" + last_result.get("error", "签到失败")
                        if not last_result.get("ok", True) else "")
    if message:
        alerts.append(node("VAlert", message, type="warning", variant="tonal", density="compact",
                           **{"class": "mb-2", "style": {"fontSize": "12px"}}))
    balance = last_result.get("balance")
    balance_node = None
    if balance and balance.get("source") == "api":
        label = "上次余额" if last_result.get("balance_error") else "积分余额"
        balance_node = node("span", f"{label} {balance['available_integral_sum']}",
                            style={"fontSize": "13px", "fontWeight": "600", "color": "rgb(var(--v-theme-primary))"})
    if not months:
        return [*alerts, node("div", "暂无签到记录", style={"textAlign": "center", "padding": "24px", "opacity": ".6"}),
                *([balance_node] if balance_node else [])]
    today = cal["today"]
    keys = [m["month"] for m in months]
    active = today[:7] if today[:7] in keys else keys[-1]
    today_points = f"+{cal['todayEarned']}" if cal.get("todaySigned") else "未签到" if cal.get("todaySigned") is False else "—"
    items = []
    for month in months:
        key = month["month"]
        year, num = map(int, key.split("-"))
        first_weekday, total = month_calendar.monthrange(year, num)
        offset = (first_weekday + 1) % 7  # Sunday first, matching the app.
        records = {d["sign_date"]: d for d in month["days"]}
        cells = [node("div", **{"aria-hidden": "true"}) for _ in range(offset)]
        for day in range(1, total + 1):
            date = f"{key}-{day:02d}"
            cells.append(_day(date, records.get(date), today))
        cells += [node("div", **{"aria-hidden": "true"}) for _ in range((-len(cells)) % 7)]
        header = node("div", f"{year}年{num}月", style={"fontSize": "20px", "fontWeight": "600", "height": "38px",
                      "lineHeight": "38px", "paddingRight": "80px", "letterSpacing": "-.3px"})
        summary = node("div", content=[node("span", text, style={"whiteSpace": "nowrap"}) for text in (
            f"连续 {cal['duration']} 天", f"今日 {today_points}",
            f"已签到 {month['signed_days']} 天", f"积分 +{month['integral']}")],
            style={"display": "flex", "justifyContent": "space-between", "flexWrap": "wrap", "columnGap": "8px",
                   "fontSize": "11px", "lineHeight": "20px", "color": "rgba(var(--v-theme-on-surface),.6)",
                   "padding": "6px 0 12px", "marginBottom": "10px", "borderBottom": "1px solid rgba(var(--v-theme-on-surface),.07)"})
        items.append(node("VWindowItem", value=key, content=[header, summary,
            node("div", content=[node("div", d, style={"textAlign": "center", "fontSize": "11px", "opacity": ".45"}) for d in "日一二三四五六"],
                 style={"display": "grid", "gridTemplateColumns": "repeat(7,minmax(0,1fr))", "gap": "6px", "marginBottom": "10px"}),
            node("div", content=cells, style={"display": "grid", "gridTemplateColumns": "repeat(7,minmax(0,1fr))", "gap": "6px", "paddingBottom": "4px"}),
        ]))
    # PageRender has no FormRender model/event expressions. VWindow owns its own
    # selection and arrows, so month navigation remains entirely client-side.
    window = node("VWindow", content=items, modelValue=active,
                  **{"show-arrows": True, "continuous": False, "touch": False, "class": "dicar-calendar-months"})
    footer = [node("span", "★ 福利积分", title="未签到的福利日为预计日期", style={"fontSize": "11px", "color": "rgb(var(--v-theme-primary))"})]
    if balance_node:
        footer.append(balance_node)
    card = node("div", content=[window, node("div", content=footer,
                style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginTop": "12px",
                       "paddingTop": "12px", "borderTop": "1px solid rgba(var(--v-theme-on-surface),.07)"})])
    css = {"component": "style", "html": (
        ".v-dialog > .v-overlay__content:has(.dicar-calendar-board){max-width:560px!important;}"
        ".v-dialog .v-card-text:has(.dicar-calendar-board){padding-top:8px!important;}"
        ".dicar-calendar-board .dicar-calendar-months .v-window__controls{"
        "top:0;bottom:auto;left:auto;right:0;width:72px;height:38px;padding:0;align-items:center;pointer-events:none;}"
        ".dicar-calendar-board .dicar-calendar-months .v-window__controls .v-btn{pointer-events:auto;width:30px;height:30px;min-width:30px;border-radius:10px;background:rgba(var(--v-theme-on-surface),.04)!important;color:inherit!important;box-shadow:none!important;}.dicar-calendar-board .dicar-calendar-months .v-window__controls .v-btn .v-icon{font-size:18px;}"
    )}
    return [node("div", content=[css, *alerts, card], **{"class": "dicar-calendar-board",
                 "style": {"maxWidth": "420px", "margin": "0 auto", "width": "100%", "fontVariantNumeric": "tabular-nums"}})]
