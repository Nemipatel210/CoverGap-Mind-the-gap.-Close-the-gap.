/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['"Public Sans"', 'system-ui', 'sans-serif'] },
      colors: {
        // Sevaro palette: deep navy for brand and headings, teal for actions, light blue-gray workspace, slate text.
        navy: { DEFAULT: '#123D56', 700: '#0E3146', 600: '#1C5170', 100: '#E3EDF3' },
        canvas: '#F3F7F9',
        line: '#DCE5EB',
        ink: { DEFAULT: '#334155', soft: '#5B6B7F', faint: '#94A3B8' },
        teal: { DEFAULT: '#087E8B', 600: '#066B76', 700: '#055A63', 50: '#E7F4F5', 100: '#C9E7EA' },
        ok: { DEFAULT: '#2F7D4F', 50: '#E9F5EE' },
        warn: { DEFAULT: '#A86A12', 50: '#FBF2E2' },
        bad: { DEFAULT: '#B83232', 50: '#FBEBEB' },
      },
      borderRadius: { xl: '0.75rem' },
    },
  },
  plugins: [],
}
