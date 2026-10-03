import { useEffect, useRef, type ReactNode } from 'react';
export function ConfirmDialog({ title, children, confirm, cancel, confirmLabel='Подтвердить', confirmDisabled=false }: { title: string; children: ReactNode; confirm: () => void; cancel: () => void; confirmLabel?:string; confirmDisabled?:boolean }) {
  const root = useRef<HTMLDivElement>(null), cancelButton = useRef<HTMLButtonElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; cancelButton.current?.focus(); return () => { if (previous?.isConnected) previous.focus(); }; }, []);
  return <div className="common-dialog-backdrop"><div ref={root} className="panel-card common-dialog" role="dialog" aria-modal="true" aria-label={title} onKeyDown={e => {
    if (e.key === 'Escape') { e.preventDefault(); cancel(); }
    if (e.key === 'Tab') { const controls = root.current?.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex="0"]'); if (!controls?.length) return; const first = controls[0], last = controls[controls.length - 1]; if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); } }
  }}><h2>{title}</h2>{children}<div className="panel-choices"><button type="button" disabled={confirmDisabled} onClick={confirm}>{confirmLabel}</button><button type="button" ref={cancelButton} onClick={cancel}>Отмена</button></div></div></div>;
}
