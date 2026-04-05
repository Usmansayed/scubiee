// Ensure store is available globally for debugging
import { store } from './app/store';
window.store = store; // This makes the store available in the console

// Ensure the profile reducer is registered
console.log('Initial Redux State:', store.getState());
console.log('Profile slice exists:', store.getState().hasOwnProperty('profile'));

// Rest of the index.js file...
