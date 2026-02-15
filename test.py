"""
Test script to directly query Gamma API for BTC markets.
Run this separately to debug the API response.
"""

import httpx
import asyncio
from datetime import datetime, timezone, timedelta
import json

async def test_gamma_api():
    """Test different filtering approaches with Gamma API."""
    
    base_url = "https://gamma-api.polymarket.com"
    now = datetime.now(timezone.utc)
    
    print("=" * 80)
    print("TESTING GAMMA API FILTERING")
    print("=" * 80)
    
    async with httpx.AsyncClient() as client:
        
        # Test 1: Get all active BTC markets (no time filter)
        print("\n1. Testing: All active BTC markets (no time filter)")
        params1 = {
            "active": "true",
            "closed": "false",
            "archived": "false",
            "limit": 50,
            "slug": "btc-updown-15m-1771140600"  # Use the specific slug we know exists
        }
        
        response1 = await client.get(f"{base_url}/markets", params=params1)
        if response1.status_code == 200:
            data1 = response1.json()
            print(f"   Found {len(data1)} markets with slug filter")
            for market in data1:
                print(f"   - {market.get('slug')}: {market.get('question')}")
        else:
            print(f"   Error: {response1.status_code}")
        
        # Test 2: Get markets with crypto tag
        print("\n2. Testing: Markets with crypto tag (744)")
        params2 = {
            "active": "true",
            "closed": "false",
            "archived": "false",
            "tag_id": 744,
            "limit": 20
        }
        
        response2 = await client.get(f"{base_url}/markets", params=params2)
        if response2.status_code == 200:
            data2 = response2.json()
            print(f"   Found {len(data2)} crypto markets")
            for market in data2[:5]:  # Show first 5
                print(f"   - {market.get('slug')}: {market.get('question')}")
        else:
            print(f"   Error: {response2.status_code}")
        
        # Test 3: Get markets with time filter (next 30 minutes)
        print("\n3. Testing: Time filter (next 30 minutes)")
        params3 = {
            "active": "true",
            "closed": "false",
            "archived": "false",
            "end_date_min": now.isoformat(),
            "end_date_max": (now + timedelta(minutes=30)).isoformat(),
            "limit": 50
        }
        
        response3 = await client.get(f"{base_url}/markets", params=params3)
        if response3.status_code == 200:
            data3 = response3.json()
            print(f"   Found {len(data3)} markets expiring in next 30 min")
            btc_markets = [m for m in data3 if 'btc' in m.get('slug', '').lower()]
            print(f"   BTC markets in this window: {len(btc_markets)}")
            for market in btc_markets:
                print(f"   - {market.get('slug')}: expires {market.get('endDate')}")
        else:
            print(f"   Error: {response3.status_code}")
        
        # Test 4: Get markets with time filter + crypto tag
        print("\n4. Testing: Time filter + crypto tag")
        params4 = {
            "active": "true",
            "closed": "false",
            "archived": "false",
            "tag_id": 744,
            "end_date_min": now.isoformat(),
            "end_date_max": (now + timedelta(minutes=30)).isoformat(),
            "limit": 50
        }
        
        response4 = await client.get(f"{base_url}/markets", params=params4)
        if response4.status_code == 200:
            data4 = response4.json()
            print(f"   Found {len(data4)} crypto markets expiring in next 30 min")
            btc_markets = [m for m in data4 if 'btc' in m.get('slug', '').lower()]
            print(f"   BTC markets: {len(btc_markets)}")
            for market in btc_markets:
                print(f"   - {market.get('slug')}")
        else:
            print(f"   Error: {response4.status_code}")

if __name__ == "__main__":
    asyncio.run(test_gamma_api())