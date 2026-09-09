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
    style = {"minWidth": "0", "minHeight": "0", "aspectRatio": "1 / 1", "boxSizing": "border-box", "padding": "3px 1px", "borderRadius": "8px", "position": "relative",
             "display": "flex", "flexDirection": "column", "alignItems": "center", "justifyContent": "center",
             "gap": "1px", "border": "1px solid transparent", "textAlign": "center"}
    if current:
        style.update(background="#edb858", color="#3e2b0e", border="1px solid #edb858")
    elif signed:
        style.update(background="rgba(227,175,87,.14)", color="rgb(var(--v-theme-on-surface))")
    elif missed:
        style.update(border="1px dashed rgba(215,164,75,.75)")
    if reward and not current:
        style.update(color="rgb(var(--v-theme-on-surface))")
    detail = "未返回记录" if record is None else f"已签到，获得 {record['integral']} 积分" if signed else "漏签" if missed else "未签到" if current else "待签到"
    if reward:
        detail += "；福利积分日" + ("（已获得）" if signed else "（以当天实际签到结果为准）")
    children = [node("div", "今日" if current else str(int(date[-2:])),
                     style={"fontSize": "clamp(13px,2vw,18px)", "fontWeight": "600"})]
    if signed:
        children.append(node("div", f"✓ +{record['integral']}", style={"fontSize": "clamp(10px,1.5vw,13px)", "fontWeight": "600"}))
    else:
        children.append(node("div", "—" if record is None else "漏签" if missed else "待签到" if current else "",
                             style={"fontSize": "11px", "opacity": ".6", "minHeight": "16px"}))
    if reward:
        children.append(node("div", "★", style={"position": "absolute", "top": "0", "right": "3px", "fontSize": "10px", "color": "#a56c10"}))
    return node("div", content=children, title=f"{date}：{detail}", **{"aria-label": f"{date}：{detail}", "style": style})


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
                            style={"fontSize": "12px", "fontWeight": "600"})
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
        header = node("div", f"{year}年{num}月", style={"fontSize": "16px", "fontWeight": "600", "height": "34px",
                      "lineHeight": "34px", "textAlign": "center"})
        summary = node("div", content=[node("span", text, style={"whiteSpace": "nowrap"}) for text in (
            f"连续 {cal['duration']} 天", f"今日 {today_points}",
            f"已签到 {month['signed_days']} 天", f"积分 +{month['integral']}")],
            style={"display": "flex", "justifyContent": "center", "flexWrap": "wrap", "columnGap": "14px",
                   "fontSize": "12px", "lineHeight": "20px", "opacity": ".7", "margin": "2px 0 10px"})
        items.append(node("VWindowItem", value=key, content=[header, summary,
            node("div", content=[node("div", d, style={"textAlign": "center", "fontSize": "13px", "opacity": ".6"}) for d in "日一二三四五六"],
                 style={"display": "grid", "gridTemplateColumns": "repeat(7,minmax(0,1fr))", "marginBottom": "6px"}),
            node("div", content=cells, style={"display": "grid", "gridTemplateColumns": "repeat(7,minmax(0,1fr))", "gap": "4px"}),
        ]))
    # PageRender has no FormRender model/event expressions. VWindow owns its own
    # selection and arrows, so month navigation remains entirely client-side.
    window = node("VWindow", content=items, modelValue=active,
                  **{"show-arrows": True, "continuous": False, "touch": False, "class": "dicar-calendar-months"})
    footer = [node("span", "★ 福利积分", title="未签到的福利日为预计日期", style={"fontSize": "11px", "opacity": ".6"})]
    if balance_node:
        footer.append(balance_node)
    card = node("div", content=[window, node("div", content=footer,
                style={"display": "flex", "justifyContent": "space-between", "marginTop": "6px"})])
    css = {"component": "style", "html": (
        ".v-dialog > .v-overlay__content:has(.dicar-calendar-board){max-width:560px!important;}"
        ".dicar-calendar-board .dicar-calendar-months .v-window__controls{"
        "top:0;bottom:auto;left:50%;transform:translateX(-50%);width:200px;height:34px;padding:0;align-items:center;pointer-events:none;}"
        ".dicar-calendar-board .dicar-calendar-months .v-window__controls .v-btn{pointer-events:auto;width:28px;height:28px;min-width:28px;background:transparent!important;color:inherit!important;box-shadow:none!important;}.dicar-calendar-board .dicar-calendar-months .v-window__controls .v-btn .v-icon{font-size:20px;}"
    )}
    return [node("div", content=[css, *alerts, card], **{"class": "dicar-calendar-board",
                 "style": {"maxWidth": "420px", "margin": "0 auto", "width": "100%"}})]
