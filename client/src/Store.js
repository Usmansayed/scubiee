// This file ensures backwards compatibility with any import from './Store'
// by re-exporting from the correct location

import { store, persistor } from './app/store';

console.log('Store.js: Re-exporting the app/store with profile reducer');
console.log('Available slices:', Object.keys(store.getState()));
console.log('Profile data in store:', store.getState().profile?.profileInfo ? 'Available' : 'Not available');

// Test if localStorage is working, to diagnose persistence issues
try {
  localStorage.setItem('storeTest', 'test');
  const testValue = localStorage.getItem('storeTest');
  console.log('LocalStorage test:', testValue === 'test' ? 'Working' : 'Failed');
  localStorage.removeItem('storeTest');
} catch (err) {
  console.error('LocalStorage not available:', err);
}

// Export the store as the default export to match previous imports
export default store;

// Also export named exports
export { store, persistor };