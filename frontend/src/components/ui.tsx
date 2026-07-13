import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  Search,
  X,
  type LucideIcon,
} from 'lucide-react';
import {
  useEffect,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'link';
type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  className = '',
  children,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={`ui-button ui-button--${variant} ui-button--${size} ${className}`.trim()}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}

export function IconButton({ label, children, ...props }: Omit<ButtonProps, 'aria-label'> & { label: string }) {
  return (
    <Button className={`ui-button--icon ${props.className || ''}`} aria-label={label} title={label} {...props}>
      {children}
    </Button>
  );
}

interface FieldProps {
  label?: string;
  help?: string;
  error?: string;
  children: ReactNode;
  className?: string;
}

export function Field({ label, help, error, children, className = '' }: FieldProps) {
  return (
    <label className={`ui-field ${className}`.trim()}>
      {label && <span className="ui-label">{label}</span>}
      {children}
      {error ? <span className="ui-field-error">{error}</span> : help ? <span className="ui-help">{help}</span> : null}
    </label>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} />;
}

export function MultiSelect(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select multiple {...props} />;
}

export function Checkbox({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return <label className="ui-control-row"><input type="checkbox" {...props} /><span>{label}</span></label>;
}

export function Radio({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return <label className="ui-control-row"><input type="radio" {...props} /><span>{label}</span></label>;
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <article className={`ui-card ${className}`.trim()}>{children}</article>;
}

export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`ui-panel ${className}`.trim()}>{children}</section>;
}

export interface TabItem<T extends string> { key: T; label: string; badge?: string | number; }

export function Tabs<T extends string>({ items, value, onChange, label }: {
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="ui-tabs" role="tablist" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          className="ui-tab"
          aria-selected={value === item.key}
          onClick={() => onChange(item.key)}
        >
          {item.label}{item.badge !== undefined ? ` (${item.badge})` : ''}
        </button>
      ))}
    </div>
  );
}

type AlertTone = 'info' | 'success' | 'warning' | 'danger';
const ALERT_ICONS: Record<AlertTone, LucideIcon> = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: AlertCircle,
};

export function Alert({ tone = 'info', title, children, className = '' }: {
  tone?: AlertTone;
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  const Icon = ALERT_ICONS[tone];
  return (
    <div className={`ui-alert ui-alert--${tone} ${className}`.trim()} role={tone === 'danger' ? 'alert' : 'status'}>
      <Icon size={17} aria-hidden="true" />
      <div className="ui-alert__body">
        {title && <div className="ui-alert__title">{title}</div>}
        <div>{children}</div>
      </div>
    </div>
  );
}

export function Toast(props: Parameters<typeof Alert>[0]) {
  return <Alert {...props} />;
}

export function Badge({ tone, children }: { tone?: AlertTone | 'neutral'; children: ReactNode }) {
  const suffix = tone && tone !== 'neutral' ? ` ui-badge--${tone}` : '';
  return <span className={`ui-badge${suffix}`}>{children}</span>;
}

export function Progress({ value, label }: { value: number; label?: string }) {
  const normalized = Math.max(0, Math.min(value, 100));
  return (
    <div>
      <div className="ui-progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={normalized}>
        <div className="ui-progress__fill" style={{ width: `${normalized}%` }} />
      </div>
    </div>
  );
}

export function Spinner() {
  return <span className="ui-spinner" aria-hidden="true" />;
}

interface StateProps {
  title: string;
  description: string;
  icon?: ReactNode;
  actions?: ReactNode;
}

export function EmptyState({ title, description, icon, actions }: StateProps) {
  return (
    <div className="ui-state">
      <div><div className="ui-state__icon">{icon || <Info size={20} />}</div><h3>{title}</h3><p>{description}</p>{actions && <div className="ui-state__actions">{actions}</div>}</div>
    </div>
  );
}

export function ErrorState({ title, description, icon, actions }: StateProps) {
  return <EmptyState title={title} description={description} icon={icon || <AlertCircle size={20} />} actions={actions} />;
}

export function Skeleton({ width = '100%', height = 16 }: { width?: string | number; height?: number }) {
  return <div className="ui-skeleton" style={{ width, height }} aria-hidden="true" />;
}

export function LoadingState({ label = '正在加载' }: { label?: string }) {
  return <div className="ui-state" role="status"><div><Spinner /><p>{label}</p></div></div>;
}

export function SectionHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="ui-section-header">
      <div><h2 className="ui-section-title">{title}</h2>{description && <p className="ui-section-description">{description}</p>}</div>
      {actions}
    </div>
  );
}

export function PageHeader({ title, description, breadcrumbs, actions }: {
  title: string;
  description?: string;
  breadcrumbs?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="ui-page-header">
      <div>{breadcrumbs && <div className="ui-breadcrumbs">{breadcrumbs}</div>}<h1 className="ui-page-title">{title}</h1>{description && <p className="ui-page-description">{description}</p>}</div>
      {actions && <div className="ui-page-actions">{actions}</div>}
    </header>
  );
}

export function SearchInput({ label = '搜索', ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  return <div className="ui-search"><Search size={16} aria-hidden="true" /><input type="search" aria-label={label} {...props} /></div>;
}

export function LongTextEditor(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`ui-long-editor ${props.className || ''}`.trim()} {...props} />;
}

export function ChapterList<T extends { id: string; title: string }>({ items, currentId, onSelect, emptyLabel = '暂无章节' }: {
  items: T[];
  currentId?: string;
  onSelect: (item: T) => void;
  emptyLabel?: string;
}) {
  if (!items.length) return <div className="ui-help">{emptyLabel}</div>;
  return <div className="ui-chapter-list">{items.map((item) => <button key={item.id} className="ui-chapter-item" aria-current={currentId === item.id} onClick={() => onSelect(item)}>{item.title}</button>)}</div>;
}

export function Modal({ open, title, onClose, children, footer }: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="ui-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="ui-modal" role="dialog" aria-modal="true" aria-labelledby="ui-modal-title">
        <div className="ui-modal__header"><h2 id="ui-modal-title" className="ui-modal__title">{title}</h2><IconButton label="关闭" variant="ghost" onClick={onClose}><X size={18} /></IconButton></div>
        <div className="ui-modal__body">{children}</div>
        {footer && <div className="ui-modal__footer">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ open, title, description, confirmLabel = '确认', danger = false, onConfirm, onClose }: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return <Modal open={open} title={title} onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</Button></>}><p style={{ margin: 0, color: 'var(--text-secondary)' }}>{description}</p></Modal>;
}
