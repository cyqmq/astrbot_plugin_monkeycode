import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import 'vuetify/styles'

import App from './App.vue'

const initialTheme =
  document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'

const vuetify = createVuetify({
  theme: {
    defaultTheme: initialTheme,
    themes: {
      light: {
        colors: {
          primary: '#2f7cf6',
          surface: '#ffffff',
          background: '#ffffff',
        },
      },
      dark: {
        colors: {
          primary: '#60a5fa',
          surface: '#23252a',
          background: '#1a1a1a',
        },
      },
    },
  },
})

const app = createApp(App)
app.use(vuetify)
app.mount('#app')