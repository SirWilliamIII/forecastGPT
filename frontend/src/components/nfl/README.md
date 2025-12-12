# NFL Forecast Timeline Components

Interactive visualization components for NFL team win probability forecasting.

## Components

### ForecastTimeline

A time series chart showing how win probability forecasts evolve over time, with event markers.

**Features:**
- Multi-source forecast visualization (ML Model, Baker API, Event-Weighted)
- Interactive time range selector (7d, 30d, 90d)
- Toggleable forecast sources via legend
- Event markers with color-coded impact (green=positive, red=negative, gray=neutral)
- Marker size indicates impact magnitude
- Detailed tooltips with delta calculations
- Responsive design with mobile support
- Recharts-based implementation

**Props:**
```typescript
interface ForecastTimelineProps {
  data: ForecastTimeline | undefined;
  isLoading: boolean;
}
```

**Usage:**
```tsx
import { ForecastTimeline } from "@/components/nfl";

<ForecastTimeline
  data={forecastTimeline}
  isLoading={timelineLoading}
/>
```

### EventImpactCard

Displays recent events and their impact on win probability, sorted by significance.

**Features:**
- Event list sorted by absolute impact
- Visual impact indicators (trending up/down icons)
- Before/after win probability comparison
- Days ago calculation
- Similar events count
- Click handler for event details
- Empty and loading states
- Explanatory footer

**Props:**
```typescript
interface EventImpactCardProps {
  impacts: EventImpact[] | undefined;
  isLoading: boolean;
  onEventClick?: (eventId: string) => void;
}
```

**Usage:**
```tsx
import { EventImpactCard } from "@/components/nfl";

<EventImpactCard
  impacts={eventImpacts}
  isLoading={impactsLoading}
  onEventClick={(id) => console.log('Clicked event:', id)}
/>
```

## API Integration

### Required Endpoints

The components expect these backend endpoints:

#### GET /nfl/forecast/timeline
Fetch forecast timeline data.

**Query params:**
- `symbol`: Team symbol (e.g., "NFL:DAL_COWBOYS")
- `days`: Number of days to fetch (default: 30)

**Response:**
```typescript
{
  symbol: string;
  timeline: Array<{
    timestamp: string;
    forecasts: {
      ml_model_v2?: { value: number; confidence: number; sample_size: number };
      baker_api?: { value: number };
      event_weighted?: { value: number; confidence: number };
    };
    event?: { id: string; title: string; impact: number };
  }>;
}
```

#### GET /nfl/forecast/event-impacts
Fetch event impact data.

**Query params:**
- `symbol`: Team symbol
- `limit`: Number of events (default: 10)

**Response:**
```typescript
Array<{
  event_id: string;
  event_title: string;
  event_date: string;
  win_prob_before: number;
  win_prob_after: number;
  impact: number;
  similar_events_count: number;
}>
```

### Mock Data

For development before backend is ready, use mock data:

```typescript
import {
  generateMockForecastTimeline,
  generateMockEventImpacts,
  USE_MOCK_DATA
} from "@/lib/mockData";

// In your component or API client:
if (USE_MOCK_DATA) {
  return generateMockForecastTimeline(symbol, days);
}
```

Set `USE_MOCK_DATA = true` in `lib/mockData.ts` to enable.

## Data Flow

1. **NFL Page** (`app/nfl/page.tsx`) fetches data via TanStack Query
2. **API Client** (`lib/api.ts`) makes HTTP requests to backend
3. **Components** receive typed data and handle loading/error states
4. **User interactions** trigger refetches and updates

## Styling

Components use:
- Tailwind CSS for styling
- Dark theme matching existing NFL page
- Lucide React icons
- Recharts for timeline visualization
- Responsive grid layout

## Performance Optimizations

- `useMemo` for data transformations
- Recharts `connectNulls` for sparse data
- Optimized re-renders with proper dependencies
- TanStack Query caching (5 min stale, 30 min garbage collection)

## Accessibility

- ARIA labels on interactive elements
- Keyboard navigation support
- Color contrast meeting WCAG AA
- Screen reader friendly tooltips
- Semantic HTML structure

## Future Enhancements

- [ ] Export timeline data to CSV
- [ ] Compare multiple teams side-by-side
- [ ] Add confidence intervals to chart
- [ ] Event filtering by type/impact
- [ ] Zoom and pan on timeline
- [ ] Annotations for key games
- [ ] Statistical significance indicators
- [ ] Real-time updates via WebSocket
