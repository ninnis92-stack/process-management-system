describe('Smoke tests', () => {
  it('health endpoint returns ok', () => {
    cy.request('/health').its('body').should('have.property', 'status', 'ok')
  })

  it('root responds', () => {
    cy.request({ url: '/', followRedirect: false }).its('status').should('be.oneOf', [200, 302])
  })
})
