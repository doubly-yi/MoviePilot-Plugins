"""优惠券展示与站点范围匹配；不推断未确认的范围枚举。"""
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
    stations = raw.get("stations")
    # 不截断适用站点，否则靠后的站点会被误判为不可用。
    ids = [str(s["stationId"]) for s in stations
           if isinstance(s, dict) and s.get("stationId")] if isinstance(stations, list) else []
    return {"id": text(raw.get("couponId")), "name": text(raw.get("couponName")),
            "kind": text(raw.get("couponTypeDesc")), "type": str(raw.get("couponType")),
            "status": str(raw.get("couponUseStatus")),
            "amount": number(raw.get("discountMoney")), "minimum": number(raw.get("conditionalMoney")),
            "rate": number(raw.get("discountRate")),
            "start": timestamp(raw.get("validStartTime")), "end": timestamp(raw.get("validEndTime")),
            "usage_start": text(raw.get("usageStartTime")), "usage_end": text(raw.get("usageEndTime")),
            "agreement": text(raw.get("couponAgreement"), 4000),
            "extra_limits": bool(raw.get("vipTypes") or raw.get("weekTypes")),
            "station_ids": ids, "scope_known": str(raw.get("selectType")) == "2" and bool(ids)}


def public_coupon(coupon, station_id, now):
    result = {k: v for k, v in coupon.items() if k not in ("station_ids", "scope_known")}
    result["scope"] = ("unknown" if not coupon["scope_known"] else
                       "match" if station_id in coupon["station_ids"] else "other") if station_id else "unselected"
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
