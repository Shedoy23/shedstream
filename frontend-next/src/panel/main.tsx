import { createRoot } from 'react-dom/client';
import { TwitchAuthStore } from '../auth';
import { IdentityBootstrap, type IdentityHelper } from '../skillgames/identity';
import { configuredApiOrigin } from '../skillgames/origin';
import { PanelController } from './controller';
import { HttpPanelTransport } from './transport';
import { PanelApp } from './PanelApp';
import './style.css';
declare global { interface Window { Twitch?: { ext?: IdentityHelper } } }
const auth = new TwitchAuthStore();
const identity = new IdentityBootstrap(auth, configuredApiOrigin);
const controller = new PanelController(new HttpPanelTransport(configuredApiOrigin, auth), auth, identity);
if (window.Twitch?.ext) identity.attach(window.Twitch.ext);
const root = document.getElementById('panel-root');
if (!root) throw new Error('Panel root is missing');
createRoot(root).render(<PanelApp controller={controller} identity={identity} />);
