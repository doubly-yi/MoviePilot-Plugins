"""优惠券展示；站点适用性以官方按站点查询的结果为准。"""
import math
from datetime import datetime, timezone, timedelta

BP_TZ = timezone(timedelta(hours=8))


def text(value, limit=200):
    return str(value or "")[:limit]


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def timestamp(value):
    try:
        date = datetime.fromisoformat(str(value))
        return (date if date.tzinfo else date.replace(tzinfo=BP_TZ)).timestamp()
    except (ValueError, TypeError):
        return None


def normalize_coupon(raw):
    return {"id": text(raw.get("couponId")), "name": text(raw.get("couponName")),
            "kind": text(raw.get("couponTypeDesc")), "type": str(raw.get("couponType")),
            "status": str(raw.get("couponUseStatus")),
            "amount": number(raw.get("discountMoney")), "minimum": number(raw.get("conditionalMoney")),
            "rate": number(raw.get("discountRate")),
            "start": timestamp(raw.get("validStartTime")), "end": timestamp(raw.get("validEndTime")),
            "usage_start": text(raw.get("usageStartTime")), "usage_end": text(raw.get("usageEndTime")),
            "agreement": text(raw.get("couponAgreement"), 4000),
            "extra_limits": bool(raw.get("vipTypes") or raw.get("weekTypes"))}


def public_coupon(coupon, station_id, now):
    result = {k: v for k, v in coupon.items()
              if k not in ("station_ids", "scope_known", "checked_station_id", "station_match")}
    # 旧缓存中的站点名单不再参与判断，刷新后由官方查询结果替换。
    result["scope"] = "unknown" if station_id else "unselected"
    if station_id and coupon.get("checked_station_id") == station_id:
        result["scope"] = "match" if coupon.get("station_match") else "other"
    result["validity"] = ("used" if coupon["status"] != "0" else
                          "unknown" if coupon["start"] is None or coupon["end"] is None else
                          "expired" if now > coupon["end"] else
                          "future" if now < coupon["start"] else "valid")
    result["expiring"] = result["validity"] == "valid" and coupon["end"] - now <= 3 * 86400
    return result


def station_summary(raw):
    result = {"id": text(raw.get("stationId"), 64), "name": text(raw.get("stationName")),
              "address": text(raw.get("address"), 500)}
    for target, source in (("available", "availableQty"), ("total", "totalQty"),
                           ("fast_available", "fastChargeAvailableQty"), ("fast_total", "fastChargeTotalQty"),
                           ("super_available", "supperChargeAvailableQty"), ("super_total", "supperChargeTotalQty"),
                           ("slow_available", "slowChargeAvailableQty"), ("slow_total", "slowChargeTotalQty"),
                           ("max_power", "maxPower")):
        result[target] = number(raw.get(source))
    return result
