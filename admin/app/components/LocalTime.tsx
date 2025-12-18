'use client';

interface LocalTimeProps {
  date: string | Date;
  showDate?: boolean;
}

export function LocalTime({ date, showDate = true }: LocalTimeProps) {
  const d = new Date(date);
  
  if (showDate) {
    return (
      <span>
        {d.toLocaleString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: 'numeric',
          minute: '2-digit',
          hour12: true
        })}
      </span>
    );
  }
  
  return (
    <span>
      {d.toLocaleTimeString(undefined, {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
      })}
    </span>
  );
}
