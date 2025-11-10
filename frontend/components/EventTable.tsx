/**
 * Events table with drill-down details.
 * 
 * Displays a table of remediation events with columns for time, test name,
 * resource, action taken, and status. Each row represents a single remediation
 * event processed by the system.
 */

/**
 * Type definition for a single remediation event.
 */
type Event = {
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
 * Props for the EventTable component.
 */
type EventTableProps = {
  events: Event[];
}

/**
 * EventTable component displays a table of remediation events.
 * 
 * @param props - Component properties
 * @param props.events - Array of remediation events to display
 * @returns The rendered events table
 */
export default function EventTable({ events }: EventTableProps) {
  /**
   * Format Unix timestamp to human-readable local time string.
   * 
   * @param timestamp - Unix timestamp in milliseconds
   * @returns Formatted date/time string
   */
  const formatTime = (timestamp: number) => {
    return new Date(timestamp).toLocaleString();
  };

  /**
   * Get Tailwind CSS classes for status badge based on status value.
   * 
   * @param status - Status string (success, failed, error)
   * @returns CSS class names for badge styling
   */
  const getStatusBadge = (status: string) => {
    const colors = {
      success: "bg-green-100 text-green-800",
      failed: "bg-red-100 text-red-800",
      error: "bg-red-100 text-red-800",
    };
    return colors[status as keyof typeof colors] || "bg-gray-100 text-gray-800";
  };

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-200">
        <h2 className="text-xl font-semibold">Recent Remediations</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Time
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Test
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Resource
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Action
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {events.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-gray-500">
                  No events yet. Trigger a test to see remediation in action.
                </td>
              </tr>
            ) : (
              events.map((event) => (
                <tr key={event.event_id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {formatTime(event.timestamp)}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-900">
                    {event.test_name}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500 max-w-xs truncate">
                    {event.resource_arn}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-900">
                    {event.action_taken}
                    {event.dry_run && (
                      <span className="ml-2 text-xs text-gray-500">(dry run)</span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span
                      className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${getStatusBadge(
                        event.status
                      )}`}
                    >
                      {event.status}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

