import {useEffect,useRef,type ReactNode} from 'react';
export function RimDialog({title,close,children}:{title:string;close:()=>void;children:ReactNode}){
  const root=useRef<HTMLDivElement>(null),closeButton=useRef<HTMLButtonElement>(null);
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;closeButton.current?.focus();return()=>{if(previous?.isConnected)previous.focus();};},[]);
  return <div className="common-dialog-backdrop"><div className="panel-card common-dialog" ref={root} role="dialog" aria-label={title} aria-modal="true" onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();close();}if(e.key==='Tab'){const controls=root.current?.querySelectorAll<HTMLElement>('button:not([disabled]),input,select,summary');if(!controls?.length)return;const first=controls[0],last=controls[controls.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}}}><h2>{title}</h2>{children}<button type="button" ref={closeButton} onClick={close}>Закрыть каталог пешки</button></div></div>;
}
