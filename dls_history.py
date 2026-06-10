from datetime import datetime
from zoneinfo import ZoneInfo
from curl_cffi import requests
import pandas as pd
import time
import os

URL = "https://st.cf.api.ftpub.net/StatsTracker_Frontline"
PLAYER_ID = "z261l1rs"
CSV_NAME = "dls_complete_history.csv"

# ── Load existing data ────────────────────────────────────────────────────────
existing_df = None
latest_known_timestamp = None

if os.path.exists(CSV_NAME):
    try:
        existing_df = pd.read_csv(CSV_NAME)
        if not existing_df.empty and "MatchTimestamp" in existing_df.columns:
            existing_df["MatchTimestamp"] = pd.to_numeric(existing_df["MatchTimestamp"], errors="coerce").astype("Int64")
            latest_known_timestamp = int(existing_df["MatchTimestamp"].max())
            print(f"Existing CSV loaded: {len(existing_df)} matches found.")
            print(f"Latest known match timestamp: {latest_known_timestamp}")
        else:
            print("Existing CSV is empty or missing MatchTimestamp — doing full fetch.")
    except Exception as e:
        print(f"Could not read existing CSV ({e}) — doing full fetch.")
else:
    print("No existing CSV found — doing full fetch.")

# ── Fetch first page ──────────────────────────────────────────────────────────
all_new_matches = []
stop_early = False

print("\nFetching first page...")

first_payload = {
    "queryType": "AWSGetUserData",
    "queryData": {
        "TId": PLAYER_ID,
        "hideOpponentName": None
    },
    "analytics": {
        "idx": None
    }
}

response = requests.post(URL, json=first_payload, impersonate="chrome")
response.raise_for_status()

data = response.json()
its = data["ITs"]

page_matches = data["Matches"]["results"]
cursor = data["Matches"].get("LEK")

# Filter out already-seen matches from this page
for m in page_matches:
    if latest_known_timestamp and int(m.get("MTm", 0)) <= latest_known_timestamp:
        stop_early = True
        break
    all_new_matches.append(m)

page = 1
print(f"Page {page} | New matches so far: {len(all_new_matches)}")

# ── Paginate ──────────────────────────────────────────────────────────────────
while cursor and not stop_early:
    page += 1

    payload = {
        "queryType": "AWSGetMatchHistory",
        "queryData": {
            "TId": PLAYER_ID,
            "ITs": its,
            "LIM": 500,
            "MTm": cursor
        },
        "analytics": {
            "origin": 0
        }
    }

    try:
        response = requests.post(URL, json=payload, impersonate="chrome")
        response.raise_for_status()

        page_data = response.json()
        matches = page_data.get("results", [])

        if not matches:
            print("No more matches found.")
            break

        for m in matches:
            if latest_known_timestamp and int(m.get("MTm", 0)) <= latest_known_timestamp:
                stop_early = True
                break
            all_new_matches.append(m)

        cursor = page_data.get("LEK")

        print(f"Page {page} | New matches so far: {len(all_new_matches)}")
        time.sleep(0.15)

    except Exception as e:
        print(f"Error on page {page}: {e}")
        break

if stop_early:
    print("Reached already-known matches — stopping early.")

print(f"\nNew matches fetched: {len(all_new_matches)}")

# ── Build rows from new matches ───────────────────────────────────────────────
print("Building rows...")
refresh_time = datetime.now(ZoneInfo("Asia/Kolkata"))
rows = []

for m in all_new_matches:
    goals_for = m["HSc"] if m.get("Hom") else m["ASc"]
    goals_against = m["ASc"] if m.get("Hom") else m["HSc"]

    penalty_for = m.get("HPe", 0) if m.get("Hom") else m.get("APe", 0)
    penalty_against = m.get("APe", 0) if m.get("Hom") else m.get("HPe", 0)

    if goals_for > goals_against:
        result = "W"
    elif goals_for < goals_against:
        result = "L"
    else:
        if penalty_for > penalty_against:
            result = "PW"
        elif penalty_for < penalty_against:
            result = "PL"
        else:
            result = "D"

    timestamp = m.get("MTm")

    try:
        match_date = datetime.utcfromtimestamp(int(timestamp))
    except:
        match_date = None

    rows.append({
        "MatchDate":        match_date,
        "MatchTimestamp":   timestamp,
        "Opponent":         m.get("TNL"),
        "OpponentShort":    m.get("TNS"),
        "Home":             m.get("Hom"),
        "Goals_For":        goals_for,
        "Goals_Against":    goals_against,
        "Penalty_For":      penalty_for,
        "Penalty_Against":  penalty_against,
        "Result":           result,
        "Went_To_Penalties": (penalty_for > 0 or penalty_against > 0),
        "Shots":            m.get("UserShots"),
        "Shots_On_Target":  m.get("UserShotsOnTarget"),
        "Possession":       m.get("UserPossession"),
        "Corners":          m.get("UserCorners"),
        "Fouls":            m.get("UserFouls"),
        "MOTM":             m.get("MOTM"),
        "Minutes":          m.get("Min"),
        "Division":         m.get("MDI"),
        "Data_Refresh_Time": refresh_time
    })

new_df = pd.DataFrame(rows)

# ── Merge with existing data ──────────────────────────────────────────────────
if existing_df is not None and not new_df.empty:
    # Update Data_Refresh_Time on existing rows to reflect latest run
    existing_df["Data_Refresh_Time"] = refresh_time
    df = pd.concat([new_df, existing_df], ignore_index=True)
elif existing_df is not None:
    print("No new matches — existing data is already up to date.")
    existing_df["Data_Refresh_Time"] = refresh_time
    df = existing_df
else:
    df = new_df

# ── Deduplicate ───────────────────────────────────────────────────────────────
before = len(df)
df["_dedup_key"] = df["MatchTimestamp"].astype(str) + "_" + df["Opponent"].astype(str)
df = df.drop_duplicates(subset="_dedup_key")
df = df.drop(columns=["_dedup_key"])
after = len(df)

if before != after:
    print(f"Removed {before - after} duplicate(s) during merge.")

# ── Sort and save ─────────────────────────────────────────────────────────────
df["MatchTimestamp"] = pd.to_numeric(df["MatchTimestamp"], errors="coerce")
df.sort_values(by="MatchTimestamp", ascending=False, inplace=True)

df.to_csv(CSV_NAME, index=False)

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n=================================")
print("REFRESH COMPLETE")
print("=================================")
print(f"New matches added : {len(new_df)}")
print(f"Total matches     : {len(df)}")
print(f"CSV File          : {CSV_NAME}")

wins          = len(df[df["Result"].isin(["W", "PW"])])
draws         = len(df[df["Result"] == "D"])
losses        = len(df[df["Result"].isin(["L", "PL"])])
penalty_wins  = len(df[df["Result"] == "PW"])
penalty_losses = len(df[df["Result"] == "PL"])

print(f"Wins              : {wins}")
print(f"Draws             : {draws}")
print(f"Losses            : {losses}")
print(f"Penalty Wins      : {penalty_wins}")
print(f"Penalty Losses    : {penalty_losses}")
