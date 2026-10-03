import { createRoot } from 'react-dom/client';
import { configuredApiOrigin } from '../skillgames/origin';
import { ConfigApp } from './ConfigApp';
import '../panel/style.css';
const root = document.getElementById('config-root');
if (!root) throw new Error('Config root is missing');
createRoot(root).render(<ConfigApp helper={window.Twitch?.ext} baseUrl={configuredApiOrigin} search={location.search} />);
