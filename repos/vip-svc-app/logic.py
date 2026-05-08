VIP_THRESHOLD_A = 5_000_000

reason_map = {
    STATUS_VIP_A: f"AUM {profile.aum:,.0f} 元超過 {VIP_THRESHOLD_A:,} 元門檻",
    STATUS_VIP_B: f"AUM {profile.aum:,.0f} 元超過 {VIP_THRESHOLD_B:,} 元門檻",
    STATUS_STANDARD: f"AUM {profile.aum:,.0f} 元未達任何 VIP 門檻",
}