def fetch_vip_status(customer_id: str) -> str:
    """
    呼叫 vip-svc API 取得指定客戶的 VIP 等級。
    VIP 門檻已更新為 500 萬。
    ...
    # 假設 vip_status 是根據客戶資產判斷，門檻改為 500 萬
    if customer_assets >= 5_000_000:
        vip_status = 'VIP'
    else:
        vip_status = 'Regular'
    return vip_status