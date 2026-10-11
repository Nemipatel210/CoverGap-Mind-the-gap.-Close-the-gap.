/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['"Public Sans"', 'system-ui', 'sans-serif'] },
      colors: {
        navy: { DEFAULT: '#13294B', 700: '#1C3863', 600: '#28497A', 100: '#E6ECF5' },
        canvas: '#F4F6F9',
        line: '#DCE2EA',
        ink: { DEFAULT: '#1B2636', soft: '#56657A', faint: '#8593A6' },
        teal: { DEFAULT: '#2A7477', 600: '#23605F', 50: '#E8F3F3', 100: '#CFE6E6' },
        ok: { DEFAULT: '#2F7D4F', 50: '#E9F5EE' },
        warn: { DEFAULT: '#A86A12', 50: '#FBF2E2' },
        bad: { DEFAULT: '#B83232', 50: '#FBEBEB' },
      },
      borderRadius: { xl: '0.75rem' },
    },
  },
  plugins: [],
}
