"""UniServe ai-core event bus (Feature 01).

Valkey-Streams publisher/consumer base classes shared by the AI pipeline. This
package owns transport only (connection, streams, publish, consume, retry, DLQ);
message schemas belong to Feature 02f and business logic to features 06-10.
"""

from app.events import streams
from app.events.consumer import BaseConsumer
from app.events.event import build_event
from app.events.publisher import BasePublisher

__all__ = ["streams", "BaseConsumer", "BasePublisher", "build_event"]
