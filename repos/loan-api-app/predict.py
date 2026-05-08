VIP_THRESHOLD = 5000000

response = _session.post(
    endpoint,
    json={"customer_id": customer_id, "vip_threshold": VIP_THRESHOLD},
    timeout=VIP_SVC_TIMEOUT,
)