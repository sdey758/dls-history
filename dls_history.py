import os
from datetime import datetime
from zoneinfo import ZoneInfo
from curl_cffi import requests
import pandas as pd
import time
from datetime import datetime

URL = "https://st.cf.api.ftpub.net/StatsTracker_Frontline"
PLAYER_ID = "z261l1rs"
csv_name = "dls_complete_history.csv"

existing_timestamps = set()

if os.path.exists(csv_name):

    old_df = pd.read_csv(csv_name)

    existing_timestamps = set(
        old_df["MatchTimestamp"]
        .astype(str)
        .tolist()
    )

    print(
        f"Existing Matches: "
        f"{len(existing_timestamps)}"
    )
all_matches = []

print("Fetching first page...")

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

response = requests.post(
    URL,
    json=first_payload,
    impersonate="chrome"
)

response.raise_for_status()

data = response.json()

its = data["ITs"]

all_matches.extend(data["Matches"]["results"])

cursor = data["Matches"].get("LEK")

page = 1

print(f"Page {page} | Matches Downloaded: {len(all_matches)}")

while cursor:

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

        response = requests.post(
            URL,
            json=payload,
            impersonate="chrome"
        )

        response.raise_for_status()

        page_data = response.json()

        matches = page_data.get("results", [])
        print(f"Matches returned: {len(matches)}")

        if not matches:
            print("No more matches found.")
            break

        all_matches.extend(matches)

        cursor = page_data.get("LEK")

        print(
            f"Page {page} | Matches Downloaded: {len(all_matches)}"
        )

        time.sleep(0.15)

    except Exception as e:
        print(f"Error on page {page}: {e}")
        break

print("\nBuilding CSV...")
refresh_time = datetime.now(
    ZoneInfo("Asia/Kolkata")
)
rows = []

seen = set()

for m in all_matches:

    timestamp = str(
        m.get("MTm")
    )

    if timestamp in existing_timestamps:
        continue

    match_id = (
        str(m.get("MTm"))
        + "_"
        + str(m.get("TNL"))
    )

    if match_id in seen:
        continue

    seen.add(match_id)

    goals_for = (
        m["HSc"]
        if m.get("Hom")
        else m["ASc"]
    )

    goals_against = (
        m["ASc"]
        if m.get("Hom")
        else m["HSc"]
    )

    penalty_for = (
        m.get("HPe", 0)
        if m.get("Hom")
        else m.get("APe", 0)
    )

    penalty_against = (
        m.get("APe", 0)
        if m.get("Hom")
        else m.get("HPe", 0)
    )

    # Result Logic
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
        match_date = datetime.utcfromtimestamp(
            int(timestamp)
        )
    except:
        match_date = None

    rows.append(
        {
            "MatchDate": match_date,
            "MatchTimestamp": timestamp,
            "Opponent": m.get("TNL"),
            "OpponentShort": m.get("TNS"),
            "Home": m.get("Hom"),

            "Goals_For": goals_for,
            "Goals_Against": goals_against,

            "Penalty_For": penalty_for,
            "Penalty_Against": penalty_against,

            "Result": result,

            "Went_To_Penalties": (
                penalty_for > 0
                or penalty_against > 0
            ),

            "Shots": m.get("UserShots"),
            "Shots_On_Target": m.get("UserShotsOnTarget"),
            "Possession": m.get("UserPossession"),
            "Corners": m.get("UserCorners"),
            "Fouls": m.get("UserFouls"),
            "MOTM": m.get("MOTM"),
            "Minutes": m.get("Min"),
            "Division": m.get("MDI"),
            "Data_Refresh_Time": refresh_time
        }
    )

df = pd.DataFrame(rows)

df.sort_values(
    by="MatchTimestamp",
    ascending=False,
    inplace=True
)

csv_name = "dls_complete_history.csv"

df.to_csv(
    csv_name,
    index=False
)

print("\n=================================")
print("DOWNLOAD COMPLETE")
print("=================================")
print(f"Total Matches: {len(df)}")
print(f"CSV File: {csv_name}")

wins = len(df[df["Result"].isin(["W", "PW"])])
draws = len(df[df["Result"] == "D"])
losses = len(df[df["Result"].isin(["L", "PL"])])

penalty_wins = len(df[df["Result"] == "PW"])
penalty_losses = len(df[df["Result"] == "PL"])

print(f"Wins           : {wins}")
print(f"Draws          : {draws}")
print(f"Losses         : {losses}")
print(f"Penalty Wins   : {penalty_wins}")
print(f"Penalty Losses : {penalty_losses}")

