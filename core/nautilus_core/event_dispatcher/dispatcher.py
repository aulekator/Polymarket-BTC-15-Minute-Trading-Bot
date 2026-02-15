"""
Event Dispatcher
Routes market events to appropriate strategies and components
"""
from typing import Dict, List, Callable, Any
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


class EventType(Enum):
    """Types of events in the system."""
    PRICE_UPDATE = "price_update"
    QUOTE_TICK = "quote_tick"
    TRADE_TICK = "trade_tick"
    SENTIMENT_UPDATE = "sentiment_update"
    ANOMALY_DETECTED = "anomaly_detected"
    SIGNAL_GENERATED = "signal_generated"
    ORDER_FILLED = "order_filled"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    RISK_ALERT = "risk_alert"


@dataclass
class Event:
    """Base event class."""
    type: EventType
    timestamp: datetime
    source: str
    data: Dict[str, Any]


class EventDispatcher:
    """
    Central event dispatcher that routes events to subscribers.
    
    Implements pub/sub pattern for loose coupling between components.
    """
    
    def __init__(self):
        """Initialize event dispatcher."""
        # Subscribers: event_type -> list of callbacks
        self._subscribers: Dict[EventType, List[Callable]] = {
            event_type: [] for event_type in EventType
        }
        
        # Event history (for debugging)
        self._event_history: List[Event] = []
        self._max_history = 1000
        
        # Statistics
        self._event_counts: Dict[EventType, int] = {
            event_type: 0 for event_type in EventType
        }
        
        logger.info("Initialized Event Dispatcher")
    
    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[Event], None],
    ) -> None:
        """
        Subscribe to an event type.
        
        Args:
            event_type: Type of event to subscribe to
            callback: Function to call when event occurs
        """
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)
            logger.debug(f"Subscribed to {event_type.value}")
    
    def unsubscribe(
        self,
        event_type: EventType,
        callback: Callable[[Event], None],
    ) -> None:
        """
        Unsubscribe from an event type.
        
        Args:
            event_type: Type of event
            callback: Callback to remove
        """
        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
            logger.debug(f"Unsubscribed from {event_type.value}")
    
    def dispatch(self, event: Event) -> None:
        """
        Dispatch event to all subscribers.
        
        Args:
            event: Event to dispatch
        """
        try:
            # Update statistics
            self._event_counts[event.type] += 1
            
            # Add to history
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)
            
            # Call all subscribers
            subscribers = self._subscribers.get(event.type, [])
            
            for callback in subscribers:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(
                        f"Error in event subscriber for {event.type.value}: {e}"
                    )
            
            logger.debug(
                f"Dispatched {event.type.value} to {len(subscribers)} subscribers"
            )
            
        except Exception as e:
            logger.error(f"Error dispatching event: {e}")
    
    def dispatch_price_update(
        self,
        source: str,
        price: float,
        metadata: Dict[str, Any] = None,
    ) -> None:
        """Convenience method to dispatch price update."""
        event = Event(
            type=EventType.PRICE_UPDATE,
            timestamp=datetime.now(),
            source=source,
            data={
                "price": price,
                **(metadata or {})
            }
        )
        self.dispatch(event)
    
    def dispatch_sentiment_update(
        self,
        source: str,
        score: float,
        classification: str,
        metadata: Dict[str, Any] = None,
    ) -> None:
        """Convenience method to dispatch sentiment update."""
        event = Event(
            type=EventType.SENTIMENT_UPDATE,
            timestamp=datetime.now(),
            source=source,
            data={
                "score": score,
                "classification": classification,
                **(metadata or {})
            }
        )
        self.dispatch(event)
    
    def dispatch_anomaly(
        self,
        source: str,
        anomaly_type: str,
        details: Dict[str, Any],
    ) -> None:
        """Convenience method to dispatch anomaly detection."""
        event = Event(
            type=EventType.ANOMALY_DETECTED,
            timestamp=datetime.now(),
            source=source,
            data={
                "anomaly_type": anomaly_type,
                **details
            }
        )
        self.dispatch(event)
    
    def dispatch_signal(
        self,
        source: str,
        signal_type: str,
        strength: float,
        metadata: Dict[str, Any] = None,
    ) -> None:
        """Convenience method to dispatch trading signal."""
        event = Event(
            type=EventType.SIGNAL_GENERATED,
            timestamp=datetime.now(),
            source=source,
            data={
                "signal_type": signal_type,
                "strength": strength,
                **(metadata or {})
            }
        )
        self.dispatch(event)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get event dispatcher statistics."""
        return {
            "total_events": sum(self._event_counts.values()),
            "events_by_type": {
                event_type.value: count
                for event_type, count in self._event_counts.items()
            },
            "subscriber_counts": {
                event_type.value: len(subscribers)
                for event_type, subscribers in self._subscribers.items()
            },
            "history_size": len(self._event_history),
        }
    
    def get_recent_events(
        self,
        event_type: EventType = None,
        limit: int = 10,
    ) -> List[Event]:
        """
        Get recent events.
        
        Args:
            event_type: Filter by event type (None for all)
            limit: Maximum number of events to return
            
        Returns:
            List of recent events
        """
        if event_type:
            events = [e for e in self._event_history if e.type == event_type]
        else:
            events = self._event_history
        
        return events[-limit:]
    
    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()
        logger.info("Cleared event history")
    
    def reset_statistics(self) -> None:
        """Reset event statistics."""
        self._event_counts = {
            event_type: 0 for event_type in EventType
        }
        logger.info("Reset event statistics")


# Singleton instance
_dispatcher_instance = None

def get_event_dispatcher() -> EventDispatcher:
    """Get singleton event dispatcher."""
    global _dispatcher_instance
    if _dispatcher_instance is None:
        _dispatcher_instance = EventDispatcher()
    return _dispatcher_instance