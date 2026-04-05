/** @type {import('tailwindcss').Config} */
const defaultTheme = require('tailwindcss/defaultTheme');


export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      
      screens: {
        'desktop': '1980px', // Custom breakpoint
        '640':'640px',
        '380':'380px',

        '400':'400px',
        '500':'500px',
        '550':'550px',
        '1800':'1800px',



      },
      animation: {
        'pulse': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        rainbow: 'rainbow 4s linear infinite',
      },
      keyframes: {
        pulse: {
          '0%, 100%': { opacity: 1 },
          '50%': { opacity: .5 },
        },
        rainbow: {
          '0%': { backgroundPosition: '0% 50%' },
          '100%': { backgroundPosition: '200% 50%' },
        },
      },
      fontFamily: {
        roboto: ['Roboto', ...defaultTheme.fontFamily.sans],
        'open-sans': ['Open Sans', ...defaultTheme.fontFamily.sans],
        lato: ['Lato', ...defaultTheme.fontFamily.sans],
        montserrat: ['Montserrat', ...defaultTheme.fontFamily.sans],
        poppins: ['Poppins', ...defaultTheme.fontFamily.sans],
        ubuntu: ['Ubuntu', ...defaultTheme.fontFamily.sans],
        merriweather: ['Merriweather', ...defaultTheme.fontFamily.serif],
        nunito: ['Nunito', ...defaultTheme.fontFamily.sans],
        oswald: ['Oswald', ...defaultTheme.fontFamily.sans],
        raleway: ['Raleway', ...defaultTheme.fontFamily.sans],
      },
    },
  },
  plugins: [],
}
