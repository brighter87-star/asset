"""Debug script to check stock info API response."""
import json
import requests
from config.settings import Settings

settings = Settings()

def get_token():
    url = f"{settings.BASE_URL}/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "appkey": settings.APP_KEY,
        "secretkey": settings.SECRET_KEY,
    }
    response = requests.post(url, json=data)
    return response.json()["token"]

def test_stock_info_api(api_id: str):
    token = get_token()

    url = f"{settings.BASE_URL}/api/dostk/stkinfo"

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json; charset=UTF-8',
        'api-id': api_id,
    }

    body = {
        "mrkt_tp": "0",  # KOSPI
    }

    print(f"\n{'='*60}")
    print(f"Testing api-id: {api_id}")
    print(f"{'='*60}")

    response = requests.post(url, headers=headers, json=body, timeout=30)

    result = response.json()

    if result.get("return_code") == 0:
        print(f"SUCCESS! return_code=0")
        if "list" in result:
            stocks = result["list"]
            print(f"Found 'list' with {len(stocks)} items")
            cont_yn = response.headers.get('cont-yn')
            print(f"cont-yn: {cont_yn}")
            if stocks:
                print(f"First 3 items:")
                for stock in stocks[:3]:
                    print(f"  code={stock.get('code')}, name={stock.get('name')}")
        return True
    else:
        msg = result.get('return_msg', 'Unknown error')
        # Decode if needed
        try:
            msg = msg.encode('latin1').decode('utf-8')
        except:
            pass
        print(f"FAILED: {msg}")
        return False

if __name__ == "__main__":
    token = get_token()
    print(f"Token: {token[:20]}...")

    # Try different api-ids
    api_ids_to_try = [
        "ka10000",  # 종목리스트?
        "ka10002",  # 다른 종목정보?
        "ka10003",
        "ka10010",
        "kt10001",
        "ka00001",
    ]

    for api_id in api_ids_to_try:
        success = test_stock_info_api(api_id)
        if success:
            break
