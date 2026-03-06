const { defineConfig } = require('cypress')

module.exports = defineConfig({
  e2e: {
    // The `baseUrl` should be provided via CI secrets or set locally when running.
    // Example: npx cypress run --config baseUrl=https://staging.example.com
    setupNodeEvents(on, config) {
      // implement node event listeners here if needed
      return config
    },
    specPattern: 'cypress/e2e/**/*.*',
    supportFile: false,
  },
})
