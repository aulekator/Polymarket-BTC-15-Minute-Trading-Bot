"""
News and Social Media Data Source
Aggregates sentiment and news related to BTC
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import httpx
from loguru import logger


class NewsSocialDataSource:
    """
    News and social media data source.
    
    Provides:
    - Crypto news articles
    - Social media sentiment
    - Fear & Greed Index
    - Trending topics
    """
    
    def __init__(self):
        """Initialize news/social data source."""
        self.session: Optional[httpx.AsyncClient] = None
        
        # API endpoints (free tier alternatives)
        self.news_api_url = "https://cryptopanic.com/api/v1/posts/"
        self.sentiment_api_url = "https://api.alternative.me/fng/"  # Fear & Greed
        
        # Cache
        self._last_sentiment: Optional[Dict[str, Any]] = None
        self._last_news: List[Dict[str, Any]] = []
        
        logger.info("Initialized News/Social data source")
    
    async def connect(self) -> bool:
        """
        Connect to APIs.
        
        Returns:
            True if connection successful
        """
        try:
            self.session = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "PolymarketBot/1.0"}
            )
            
            # Test connection with Fear & Greed Index (no API key needed)
            response = await self.session.get(self.sentiment_api_url)
            response.raise_for_status()
            
            logger.info("✓ Connected to News/Social APIs")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to News APIs: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Close connections."""
        if self.session:
            await self.session.aclose()
            logger.info("Disconnected from News/Social APIs")
    
    async def get_fear_greed_index(self) -> Optional[Dict[str, Any]]:
        """
        Get Fear & Greed Index (0-100).
        
        Returns:
            Dict with value, classification, and timestamp
        """
        try:
            response = await self.session.get(self.sentiment_api_url)
            response.raise_for_status()
            
            data = response.json()
            current = data["data"][0]
            
            sentiment = {
                "timestamp": datetime.fromtimestamp(int(current["timestamp"])),
                "value": int(current["value"]),  # 0-100
                "classification": current["value_classification"],  # "Extreme Fear", "Fear", etc.
                "time_until_update": current.get("time_until_update"),
            }
            
            self._last_sentiment = sentiment
            
            logger.debug(f"Fear & Greed Index: {sentiment['value']} ({sentiment['classification']})")
            return sentiment
            
        except Exception as e:
            logger.error(f"Error fetching Fear & Greed Index: {e}")
            return None
    
    async def get_crypto_news(
        self,
        filter_: str = "hot",  # "rising", "hot", "bullish", "bearish"
        currencies: str = "BTC",
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get crypto news from CryptoPanic.
        
        Note: Free tier has rate limits. Consider caching.
        
        Args:
            filter_: News filter type
            currencies: Comma-separated currency codes
            limit: Max number of articles
            
        Returns:
            List of news articles
        """
        try:
            # Note: CryptoPanic free tier requires API key
            # This is a placeholder - you'll need to sign up at cryptopanic.com
            params = {
                "auth_token": "YOUR_CRYPTOPANIC_API_KEY",  # Get from cryptopanic.com
                "filter": filter_,
                "currencies": currencies,
                "public": "true",
            }
            
            response = await self.session.get(self.news_api_url, params=params)
            
            # If no API key, return cached or empty
            if response.status_code == 401:
                logger.warning("CryptoPanic API key not configured - using cached news")
                return self._last_news
            
            response.raise_for_status()
            data = response.json()
            
            news = []
            for article in data.get("results", [])[:limit]:
                news.append({
                    "timestamp": datetime.fromisoformat(article["published_at"].replace("Z", "+00:00")),
                    "title": article["title"],
                    "url": article["url"],
                    "source": article["source"]["title"],
                    "votes": article.get("votes", {}).get("positive", 0) - article.get("votes", {}).get("negative", 0),
                    "sentiment": "positive" if article.get("votes", {}).get("positive", 0) > article.get("votes", {}).get("negative", 0) else "negative",
                })
            
            self._last_news = news
            return news
            
        except Exception as e:
            logger.error(f"Error fetching crypto news: {e}")
            return self._last_news
    
    async def get_sentiment_score(self) -> Optional[float]:
        """
        Calculate aggregate sentiment score (0-100).
        
        Combines Fear & Greed Index with news sentiment.
        
        Returns:
            Sentiment score (0=extreme fear, 100=extreme greed)
        """
        try:
            # Get Fear & Greed Index
            fg_data = await self.get_fear_greed_index()
            if not fg_data:
                return None
            
            fg_score = fg_data["value"]
            
            # Try to get news sentiment
            news = await self.get_crypto_news(limit=10)
            
            if news:
                # Calculate news sentiment
                positive_count = sum(1 for n in news if n.get("sentiment") == "positive")
                news_score = (positive_count / len(news)) * 100
                
                # Weighted average (70% Fear & Greed, 30% News)
                total_score = (fg_score * 0.7) + (news_score * 0.3)
            else:
                total_score = fg_score
            
            logger.info(f"Aggregate sentiment score: {total_score:.1f}")
            return total_score
            
        except Exception as e:
            logger.error(f"Error calculating sentiment score: {e}")
            return None
    
    async def get_trending_topics(self) -> List[str]:
        """
        Get trending crypto topics.
        
        Returns:
            List of trending topics/hashtags
        """
        # This would require Twitter API or similar
        # Placeholder implementation
        return ["BTC", "Bitcoin", "Cryptocurrency", "Trading"]
    
    @property
    def last_sentiment(self) -> Optional[Dict[str, Any]]:
        """Get cached sentiment data."""
        return self._last_sentiment
    
    @property
    def last_news(self) -> List[Dict[str, Any]]:
        """Get cached news articles."""
        return self._last_news
    
    async def health_check(self) -> bool:
        """
        Check if data source is healthy.
        
        Returns:
            True if healthy
        """
        try:
            sentiment = await self.get_fear_greed_index()
            return sentiment is not None
        except:
            return False


# Singleton instance
_news_instance: Optional[NewsSocialDataSource] = None

def get_news_social_source() -> NewsSocialDataSource:
    """Get singleton instance of News/Social data source."""
    global _news_instance
    if _news_instance is None:
        _news_instance = NewsSocialDataSource()
    return _news_instance