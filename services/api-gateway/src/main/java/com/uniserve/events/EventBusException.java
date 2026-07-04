package com.uniserve.events;

/** Raised when an event cannot be serialized or written to the event bus. */
public class EventBusException extends RuntimeException {

    public EventBusException(String message, Throwable cause) {
        super(message, cause);
    }
}
