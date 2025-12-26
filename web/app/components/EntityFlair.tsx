'use client';

/**
 * EntityFlair - Displays entity badge with domain-based color coding
 * 
 * Shows the civic entity (City Council, School Board, Library, etc.) with
 * consistent color theming based on domain (civic, education, community, etc.)
 */

// Domain color definitions matching twinsburg.yaml color_schemes
const domainColors: Record<string, {
  primary: string;
  light: string;
  dark: string;
  border: string;
  icon: string;
}> = {
  civic: {
    primary: 'text-blue-600',
    light: 'bg-blue-100',
    dark: 'bg-blue-800',
    border: 'border-blue-300',
    icon: '🏛️',
  },
  education: {
    primary: 'text-purple-600',
    light: 'bg-purple-100',
    dark: 'bg-purple-800',
    border: 'border-purple-300',
    icon: '🎓',
  },
  community: {
    primary: 'text-amber-600',
    light: 'bg-amber-100',
    dark: 'bg-amber-800',
    border: 'border-amber-300',
    icon: '🤝',
  },
  recreation: {
    primary: 'text-green-600',
    light: 'bg-green-100',
    dark: 'bg-green-800',
    border: 'border-green-300',
    icon: '🌳',
  },
  business: {
    primary: 'text-slate-600',
    light: 'bg-slate-100',
    dark: 'bg-slate-800',
    border: 'border-slate-300',
    icon: '💼',
  },
};

// Default colors for unknown domains
const defaultColors = {
  primary: 'text-gray-600',
  light: 'bg-gray-100',
  dark: 'bg-gray-800',
  border: 'border-gray-300',
  icon: '📍',
};

export interface EntityInfo {
  entity_key?: string;
  entity_display_name?: string;
  entity_short_name?: string;
  entity_domain?: string;
  entity_icon?: string;
}

interface EntityFlairProps {
  entity?: EntityInfo | null;
  size?: 'sm' | 'md' | 'lg';
  showIcon?: boolean;
  variant?: 'badge' | 'pill' | 'chip';
  className?: string;
}

export function EntityFlair({ 
  entity, 
  size = 'sm', 
  showIcon = true,
  variant = 'pill',
  className = '' 
}: EntityFlairProps) {
  if (!entity || !entity.entity_display_name) {
    return null;
  }

  const domain = entity.entity_domain || 'civic';
  const colors = domainColors[domain] || defaultColors;
  const icon = entity.entity_icon || colors.icon;
  const displayName = entity.entity_short_name || entity.entity_display_name;

  // Size classes
  const sizeClasses = {
    sm: 'text-xs px-2 py-0.5',
    md: 'text-sm px-2.5 py-1',
    lg: 'text-base px-3 py-1.5',
  };

  // Variant classes
  const variantClasses = {
    badge: `${colors.light} ${colors.primary} font-semibold rounded`,
    pill: `${colors.light} ${colors.primary} font-medium rounded-full`,
    chip: `${colors.light} ${colors.primary} font-medium rounded-lg border ${colors.border}`,
  };

  return (
    <span 
      className={`inline-flex items-center gap-1 ${sizeClasses[size]} ${variantClasses[variant]} ${className}`}
      title={entity.entity_display_name}
    >
      {showIcon && <span className="flex-shrink-0">{icon}</span>}
      <span>{displayName}</span>
    </span>
  );
}

/**
 * EntityFlairGroup - Displays entity with optional city/parent context
 */
interface EntityFlairGroupProps {
  entity?: EntityInfo | null;
  cityName?: string;
  showCity?: boolean;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function EntityFlairGroup({
  entity,
  cityName = 'Twinsburg',
  showCity = false,
  size = 'sm',
  className = '',
}: EntityFlairGroupProps) {
  return (
    <div className={`inline-flex items-center gap-1.5 ${className}`}>
      {showCity && (
        <>
          <span className={`text-${size === 'sm' ? 'xs' : 'sm'} text-muted-foreground`}>
            {cityName}
          </span>
          <span className="text-muted-foreground">›</span>
        </>
      )}
      <EntityFlair entity={entity} size={size} />
    </div>
  );
}

/**
 * DomainBadge - Simple domain indicator without full entity info
 */
interface DomainBadgeProps {
  domain: string;
  size?: 'sm' | 'md';
  className?: string;
}

export function DomainBadge({ domain, size = 'sm', className = '' }: DomainBadgeProps) {
  const colors = domainColors[domain] || defaultColors;
  const sizeClasses = size === 'sm' ? 'w-2 h-2' : 'w-3 h-3';
  
  const domainLabels: Record<string, string> = {
    civic: 'City Government',
    education: 'Education',
    community: 'Community',
    recreation: 'Recreation',
    business: 'Business',
  };

  return (
    <span 
      className={`inline-flex items-center gap-1 ${className}`}
      title={domainLabels[domain] || domain}
    >
      <span className={`${sizeClasses} rounded-full ${colors.light} border ${colors.border}`} />
    </span>
  );
}

export default EntityFlair;
