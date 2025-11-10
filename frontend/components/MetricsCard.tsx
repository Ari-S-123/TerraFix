/**
 * Reusable metrics card component.
 * 
 * Displays a metric title, value, and trend information in a card format.
 * Used to show key performance indicators on the dashboard.
 */

/**
 * Props for the MetricsCard component.
 */
type MetricsCardProps = {
  title: string;
  value: string | number;
  trend: string;
}

/**
 * MetricsCard component displays a single metric with title, value, and trend.
 * 
 * @param props - Component properties
 * @param props.title - The metric title (e.g., "Total Remediations")
 * @param props.value - The metric value (e.g., 42 or "95.5%")
 * @param props.trend - Trend description (e.g., "+12% from last hour")
 * @returns The rendered metrics card
 */
export default function MetricsCard({ title, value, trend }: MetricsCardProps) {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-sm font-medium text-gray-500 mb-2">{title}</h3>
      <p className="text-3xl font-bold text-gray-900 mb-1">{value}</p>
      <p className="text-sm text-gray-600">{trend}</p>
    </div>
  );
}

