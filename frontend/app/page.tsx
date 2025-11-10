/**
 * Main dashboard page for self-healing cloud monitoring.
 * 
 * Displays real-time remediation events, metrics, and test trigger UI.
 * This component fetches events from DynamoDB via an API route and updates
 * the display every 5 seconds for real-time monitoring.
 */

"use client";

import { useState, useEffect } from "react";
import EventTable from "@/components/EventTable";
import MetricsCard from "@/components/MetricsCard";
import TriggerButton from "@/components/TriggerButton";

/**
 * Type definition for remediation event records.
 */
type RemediationEvent = {
  event_id: string;
  timestamp: number;
  test_name: string;
  resource_arn: string;
  diagnosis: string;
  remediation_command: string;
  action_taken: string;
  status: string;
  dry_run: boolean;
}

/**
 * Dashboard component that displays remediation events and metrics.
 * 
 * @returns The rendered dashboard page
 */
export default function Dashboard() {
  const [events, setEvents] = useState<RemediationEvent[]>([]);
  const [loading, setLoading] = useState(true);

  /**
   * Fetch events from DynamoDB via API route.
   * Polls every 5 seconds for real-time updates.
   */
  useEffect(() => {
    const fetchEvents = async () => {
      try {
        const response = await fetch("/api/events");
        if (!response.ok) throw new Error("Failed to fetch events");
        const data = await response.json();
        setEvents(data.events);
        setLoading(false);
      } catch (error) {
        console.error("Error fetching events:", error);
        setLoading(false);
      }
    };

    fetchEvents();
    const interval = setInterval(fetchEvents, 5000);
    return () => clearInterval(interval);
  }, []);

  const successCount = events.filter((e) => e.status === "success").length;
  const successRate =
    events.length > 0 ? ((successCount / events.length) * 100).toFixed(1) : "0.0";
  const avgResponseTime = "2.3"; // Placeholder - calculate from timestamps

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-4xl font-bold mb-2">Self-Healing Cloud Dashboard</h1>
        <p className="text-gray-600 mb-8">
          Real-time compliance remediation monitoring
        </p>

        {/* Metrics */}
        <div className="grid grid-cols-3 gap-6 mb-8">
          <MetricsCard
            title="Total Remediations"
            value={events.length}
            trend="+12% from last hour"
          />
          <MetricsCard
            title="Success Rate"
            value={`${successRate}%`}
            trend="Target: 95%"
          />
          <MetricsCard
            title="Avg Response Time"
            value={`${avgResponseTime}s`}
            trend="-0.5s improvement"
          />
        </div>

        {/* Trigger Test */}
        <div className="mb-8">
          <TriggerButton />
        </div>

        {/* Events Table */}
        {loading ? (
          <div className="text-center py-12">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
            <p className="mt-4 text-gray-600">Loading events...</p>
          </div>
        ) : (
          <EventTable events={events} />
        )}
      </div>
    </div>
  );
}

