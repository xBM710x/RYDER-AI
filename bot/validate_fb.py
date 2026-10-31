"""Validate the rugcheck backup on history: coins rugcheck flagged (pre-outage) + rugged, vs coins that passed rugcheck. Safety gates only
(lp, Token-2022 extensions, mutable metadata, transfer fee, top-10 ex-AMM, identical-bag/sniper holder patterns, reused rug assets).
Dev-history / bundle / holder-cluster / sell-sim run after these in live mode and can only reject more."""
import sqlite3, json, sys, time, collections
import rcfallback, brain2, more
from common import dex_market, CFG
c = sqlite3.connect("desk.db")
RC_REASONS = ("lp_locked", "top10", "mutable_meta", "honeypot", "bundled", "bundle_sizes", "sniper_wallets", "dev_rugs", "clone_contract")
flag = {}
for m, s, d in c.execute("SELECT mint, symbol, data FROM events WHERE kind='kill' ORDER BY id"):
    j = json.loads(d)
    if j["reason"] in RC_REASONS and ":fail" in j.get("detail", "") and "rugcheck unavailable" not in j["detail"]: flag.setdefault(m, (s, j["reason"]))
for m, s in (("6sDy3A49MGekGQjsUmXsihvVhmjCtcS2ERnSf5aWpump", "CHIPCR"), ("7DBfQd2mRCE1hkANTSxXbu5NjvewWX1DwThsrunvpump", "Qcatom")): flag[m] = (s, "rugged after 402 pass")
safe = {}
for m, s in c.execute("SELECT mint, symbol FROM events WHERE kind='score'"): safe.setdefault(m, (s, "passed rugcheck"))
safe["DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"] = ("BONK", "blue chip"); safe["EKpQGSJtjMFqKZ9KQanSqYXRcF8fBAmw6Hq7tRNy4K8m"] = ("WIF", "blue chip")
def gate(m, p):
    rc, why = rcfallback.report(m, p)
    if not rc: return "reject", why
    if rc["_lp"][0] != "pass": return "reject", "lp: " + rc["_lp"][1]
    if any("extension" in r["name"] for r in rc["risks"]): return "reject", rc["risks"][0]["name"]
    if rc["tokenMeta"].get("mutable"): return "reject", "mutable metadata"
    if rc.get("transferFee"): return "reject", "transfer fee"
    if rc["token"]["mintAuthority"] or rc["token"]["freezeAuthority"]: return "reject", "mint/freeze authority"
    k = rc["knownAccounts"]; th = [h for h in rc["topHolders"] if h["owner"] not in k]; t10 = sum(h["pct"] for h in th[:10])
    if t10 > CFG["MAX_TOP10"]: return "reject", f"top10 {t10:.1f}%"
    hv = brain2.holder_verdict(brain2.holder_scores(rc))
    if hv: return "reject", hv[1]
    pk = more.precheck(m, p, rc)
    if pk: return "reject", pk[1]
    return "pass", f"lp {rc['_lp'][1][:40]}; top10 {t10:.1f}%"
out = {}
for name, S in (("flagged_or_rugged", flag), ("passed_rugcheck", safe)):
    ms = list(S); mk = {}
    for i in range(0, len(ms), 30): mk.update(dex_market(ms[i:i + 30]))
    rows = []
    for m in ms:
        try: v, why = gate(m, mk.get(m))
        except Exception as e: v, why = "reject", f"error {str(e)[:60]}"
        rows.append(dict(mint=m, sym=S[m][0], src=S[m][1], dex=(mk.get(m) or {}).get("dexId"), verdict=v, why=why))
    out[name] = dict(n=len(rows), passed=sum(r["verdict"] == "pass" for r in rows), rejected=sum(r["verdict"] != "pass" for r in rows),
                     why=collections.Counter(r["why"].split(":")[0].split(" (")[0][:40] for r in rows if r["verdict"] != "pass").most_common(8), rows=rows)
json.dump(out, open("reports/validate_fb.json", "w"), indent=1)
for k, v in out.items(): print(k, v["n"], "pass", v["passed"], "reject", v["rejected"], v["why"]); [print("  PASS", r["sym"], r["src"], r["dex"], r["why"]) for r in v["rows"] if r["verdict"] == "pass"]
