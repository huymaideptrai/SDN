import { IconAlert, IconInbox, IconRefresh } from './icons';

export const Card = ({ title, subtitle, actions, children, flush = false, className = '' }) => (
    <section className={`card ${className}`}>
        {(title || actions) && (
            <header className="card-header">
                <div>
                    {title && <h2 className="card-title">{title}</h2>}
                    {subtitle && <p className="card-subtitle">{subtitle}</p>}
                </div>
                {actions}
            </header>
        )}
        <div className={`card-body ${flush ? 'flush' : ''}`}>{children}</div>
    </section>
);

export const Spinner = () => <span className="spinner" role="status" aria-label="Đang tải" />;

export const Button = ({ variant = 'default', size, loading = false, icon, children, className = '', ...rest }) => {
    const cls = ['btn', variant !== 'default' && `btn-${variant}`, size && `btn-${size}`, className].filter(Boolean).join(' ');
    return (
        <button className={cls} disabled={loading || rest.disabled} {...rest}>
            {loading ? <Spinner /> : icon}
            {children}
        </button>
    );
};

export const Badge = ({ tone, children }) => (
    <span className={`badge ${tone ? `badge-${tone}` : ''}`}>{children}</span>
);

export const Skeleton = ({ width = '100%', height = 14, style }) => (
    <span className="skeleton" style={{ display: 'block', width, height, ...style }} aria-hidden="true" />
);

export const EmptyState = ({ title, description, icon = <IconInbox size={20} /> }) => (
    <div className="state">
        <div className="state-icon">{icon}</div>
        <p className="state-title">{title}</p>
        {description && <p className="state-desc">{description}</p>}
    </div>
);

export const ErrorState = ({ title = 'Không tải được dữ liệu', message, onRetry }) => (
    <div className="state error" role="alert">
        <div className="state-icon"><IconAlert size={20} /></div>
        <p className="state-title">{title}</p>
        {message && <p className="state-desc">{message}</p>}
        {onRetry && (
            <Button size="sm" icon={<IconRefresh size={14} />} onClick={onRetry} style={{ marginTop: 8 }}>
                Thử lại
            </Button>
        )}
    </div>
);

export const Alert = ({ tone = 'info', icon = <IconAlert size={16} />, children }) => (
    <div className={`alert alert-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
        <span className="alert-icon">{icon}</span>
        <div>{children}</div>
    </div>
);

export const Field = ({ label, hint, htmlFor, children }) => (
    <div className="field">
        <label className="label" htmlFor={htmlFor}>{label}</label>
        {children}
        {hint && <span className="hint">{hint}</span>}
    </div>
);
