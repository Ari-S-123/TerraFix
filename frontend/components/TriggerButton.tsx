/**
 * Button to manually trigger test events.
 * 
 * This component provides a UI for manually triggering compliance test failure
 * events to the EventBridge bus. Used for testing and demonstration purposes.
 */

"use client";

import { useState } from "react";

/**
 * TriggerButton component for manually triggering test events.
 * 
 * When clicked, sends a test compliance failure event to EventBridge which
 * triggers the Lambda remediation workflow.
 * 
 * @returns The rendered trigger button with status message
 */
export default function TriggerButton() {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  /**
   * Trigger a test compliance failure event.
   * Sends event directly to EventBridge via API route.
   */
  const triggerTestEvent = async () => {
    setLoading(true);
    setMessage("");

    try {
      const response = await fetch("/api/trigger", {
        method: "POST",
      });

      if (!response.ok) throw new Error("Failed to trigger event");

      const data = await response.json();
      setMessage(`✓ Test event triggered: ${data.eventId}`);
    } catch (error) {
      setMessage("✗ Error triggering test event");
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center gap-4">
      <button
        onClick={triggerTestEvent}
        disabled={loading}
        className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-semibold px-6 py-3 rounded-lg transition-colors"
      >
        {loading ? "Triggering..." : "🚀 Trigger Test Event"}
      </button>
      {message && (
        <p className={`text-sm ${message.startsWith("✓") ? "text-green-600" : "text-red-600"}`}>
          {message}
        </p>
      )}
    </div>
  );
}

