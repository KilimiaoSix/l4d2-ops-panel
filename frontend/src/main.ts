import { createApp } from 'vue'
import App from './App.vue'
import { onUnauthorized } from './api/client'
import { router, upgradeLegacyHash } from './router'
import { session } from './stores/session'
import './styles/app.css'

upgradeLegacyHash()
onUnauthorized(() => session.loggedOut())
createApp(App).use(router).mount('#app')
