import { createRoot } from 'react-dom/client';
import { Provider } from 'react-redux';
import App from './App.jsx';
import { store, persistor } from './app/store';
import { BrowserRouter } from 'react-router-dom';
import React from 'react';
import './index.css';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { PersistGate } from 'redux-persist/integration/react';
import { MediaCacheProvider } from './context/MediaCacheContext';
const cloud = import.meta.env.VITE_CLOUD_URL;
import { registerSW } from 'virtual:pwa-register';
registerSW(); // This automatically registers and updates the SW

// Import all font styles
import '@fontsource/roboto';
import '@fontsource/roboto/700.css';
import '@fontsource/roboto/500.css';
import '@fontsource/open-sans';
import '@fontsource/open-sans/500.css';
import '@fontsource/lato';
import '@fontsource/lato/700.css';
import '@fontsource/montserrat';
import '@fontsource/montserrat/500.css';
import '@fontsource/montserrat/700.css';
import '@fontsource/poppins';
import '@fontsource/ubuntu';
import '@fontsource/merriweather';
import '@fontsource/nunito';
import '@fontsource/oswald';
import '@fontsource/raleway';
import '@fontsource/raleway/400.css';
import '@fontsource/ubuntu/500.css';

// Make the store available globally for debugging
window.store = store;

// Enhanced debug logging for Redux state initialization
console.log('Initial Redux State:', store.getState());
console.log('Available slices:', Object.keys(store.getState()));

// Add debugging for PersistGate to see when rehydration completes
const onBeforeLift = () => {
  console.log('Redux persist: Before state rehydration');
};

const onAfterLift = () => {
  console.log('Redux persist: State rehydration COMPLETE');
};

createRoot(document.getElementById('root')).render(
  <Provider store={store}>
    <PersistGate 
      loading={null} 
      persistor={persistor} 
      onBeforeLift={onBeforeLift}
      onAfterLift={onAfterLift}
    >
      <BrowserRouter>
        <MediaCacheProvider>
            <App />
        </MediaCacheProvider>
      </BrowserRouter>
    </PersistGate>
  </Provider>
);