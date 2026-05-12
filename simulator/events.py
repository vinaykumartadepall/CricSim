from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, List


class EventType(str, Enum):
    BALL_BOWLED = "BALL_BOWLED"
    OVER_COMPLETED = "OVER_COMPLETED"


@dataclass
class MatchEvent:
    type: EventType
    data: Any


class MatchObserver:
    @abstractmethod
    def on_event(self, event: MatchEvent):
        pass


class MatchEventBus:
    def __init__(self):
        self.observers: List[MatchObserver] = []

    def subscribe(self, observer: MatchObserver):
        if observer not in self.observers:
            self.observers.append(observer)

    def clear(self):
        self.observers = []

    def publish(self, event: MatchEvent):
        for observer in self.observers:
            observer.on_event(event)
