/**
 * VIKMO DEALERDESK — FRONTEND APPLICATION
 * Modular, clean JavaScript. No AI slop patterns.
 * ES Modules with proper separation of concerns.
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

const CONFIG = {
  apiBase: '/api',
  pageSize: 18,
  debounceMs: 300,
  toastDuration: 3200,
};

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

const state = {
  cart: {},
  currentPage: 1,
  totalPages: 1,
  currentDraftOrder: null,
  activeDealerId: null,
  sessionId: `session-${Math.random().toString(36).slice(2, 9)}`,
  searchDebounceTimer: null,
};

// ============================================================================
// UTILITIES
// ============================================================================

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function formatCurrency(value) {
  const num = typeof value === 'string' ? parseFloat(value) : value;
  return `₹${num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(isoString) {
  return new Date(isoString).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true
  });
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ============================================================================
// TOAST NOTIFICATIONS
// ============================================================================

const Toast = {
  container: null,

  init() {
    this.container = $('#toast-container');
    if (!this.container) {
      this.container = document.createElement('div');
      this.container.id = 'toast-container';
      document.body.appendChild(this.container);
    }
  },

  show(message, type = 'success') {
    if (!this.container) this.init();

    const toast = document.createElement('div');
    toast.className = `toast ${type === 'error' ? 'toast-error' : ''}`;
    toast.textContent = message;
    this.container.appendChild(toast);

    setTimeout(() => {
      toast.style.transition = 'all 0.25s ease';
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%) scale(0.95)';
      setTimeout(() => toast.remove(), 250);
    }, CONFIG.toastDuration);
  },

  success(msg) { this.show(msg, 'success'); },
  error(msg) { this.show(msg, 'error'); },
};

// ============================================================================
// API CLIENT
// ============================================================================

const Api = {
  async request(endpoint, options = {}) {
    const url = `${CONFIG.apiBase}${endpoint}`;
    const defaultHeaders = { 'Content-Type': 'application/json' };
    const res = await fetch(url, { ...options, headers: { ...defaultHeaders, ...options.headers } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error?.message || `HTTP ${res.status}`);
    return data;
  },

  // Products
  getProducts(params = {}) {
    const search = new URLSearchParams({ page_size: CONFIG.pageSize, ...params });
    return this.request(`/products/?${search}`);
  },

  // Dealers
  getDealers(params = {}) {
    const search = new URLSearchParams({ page_size: 50, ...params });
    return this.request(`/dealers/?${search}`);
  },

  // Orders
  getOrders(params = {}) {
    const search = new URLSearchParams({ page_size: 20, ...params });
    return this.request(`/orders/?${search}`);
  },

  createDraftOrder(dealerId, items) {
    return this.request('/orders/', {
      method: 'POST',
      body: JSON.stringify({ dealer_id: dealerId, items })
    });
  },

  confirmOrder(orderNumber) {
    return this.request(`/orders/${orderNumber}/confirm/`, { method: 'POST' });
  },

  dispatchOrder(orderNumber) {
    return this.request(`/orders/${orderNumber}/dispatch/`, { method: 'POST' });
  },

  deliverOrder(orderNumber) {
    return this.request(`/orders/${orderNumber}/deliver/`, { method: 'POST' });
  },

  cancelOrder(orderNumber) {
    return this.request(`/orders/${orderNumber}/cancel/`, { method: 'POST' });
  },

  // Assistant
  chat(message, dealerId) {
    return this.request('/assistant/chat/', {
      method: 'POST',
      body: JSON.stringify({ session_id: state.sessionId, dealer_id: dealerId, message })
    });
  },

  // Reorder / Forecast
  getReorderSuggestions() { return this.request('/reorder-suggestions/'); },
  getForecast(sku) { return this.request(`/forecast/${sku}/`); },

  // Supplier Sync
  triggerSync() { return this.request('/sync/supplier/', { method: 'POST' }); },

  // Dashboard metrics
  getDashboardMetrics(dealerId = null) { 
    const params = dealerId ? `?dealer_id=${dealerId}` : '';
    return this.request(`/dashboard/metrics/${params}`); 
  },

  async bulkUpload(formData) {
    const url = `${CONFIG.apiBase}/products/bulk-upload/`;
    const res = await fetch(url, { method: 'POST', body: formData });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error?.message || `HTTP ${res.status}`);
    return data;
  },
};

// ============================================================================
// RENDERERS — Pure functions that return HTML strings
// ============================================================================

const Render = {
  productCard(product) {
    const stockClass = product.stock === 0 ? 'stock-out' :
                       product.stock < 15 ? 'stock-low' : 'stock-in';
    const stockText = product.stock === 0 ? 'Out of Stock' :
                      product.stock < 15 ? `Low: ${product.stock} units` :
                      `${product.stock} in stock`;

    return `
      <article class="product-card" data-sku="${escapeHtml(product.sku)}">
        <div>
          <div class="product-top">
            <span class="sku-badge">${escapeHtml(product.sku)}</span>
            <span class="brand-tag">${escapeHtml(product.brand)}</span>
          </div>
          <h3 class="product-title">${escapeHtml(product.name)}</h3>
          <div class="product-meta">
            <span class="meta-pill">${escapeHtml(product.category)}</span>
            <span class="meta-pill">${escapeHtml(product.vehicle_fitment)}</span>
          </div>
        </div>
        <div>
          <div class="product-pricing-stock">
            <span class="price-value">${formatCurrency(product.price)}</span>
            <span class="stock-badge ${stockClass}">${escapeHtml(stockText)}</span>
          </div>
          <div class="qty-add-bar">
            <div class="qty-stepper" data-sku="${escapeHtml(product.sku)}">
              <button class="qty-btn" data-action="decrement" aria-label="Decrease quantity">−</button>
              <input type="text" class="qty-input" value="1" readonly aria-label="Quantity">
              <button class="qty-btn" data-action="increment" aria-label="Increase quantity">+</button>
            </div>
            <button class="btn btn-primary btn-full" data-action="add-to-cart"
              data-product='${escapeHtml(JSON.stringify(product))}'>
              Add to Cart
            </button>
          </div>
        </div>
      </article>
    `;
  },

  cartItem(sku, item) {
    const lineSub = (parseFloat(item.product.price) * item.quantity).toFixed(2);
    const lineTax = (lineSub * 0.18).toFixed(2);
    return `
      <div class="cart-item" data-sku="${escapeHtml(sku)}"
        style="display:flex;justify-content:space-between;align-items:center;padding:0.85rem 0;border-bottom:1px solid var(--color-border-subtle);">
        <div>
          <div style="font-weight:600;font-size:var(--text-base);color:var(--color-text-primary);">${escapeHtml(item.product.name)}</div>
          <div style="font-family:var(--font-mono);font-size:var(--text-xs);color:var(--color-text-secondary);margin-top:2px;">${escapeHtml(sku)} · ${formatCurrency(item.product.price)} each</div>
        </div>
        <div style="display:flex;align-items:center;gap:1rem;">
          <div class="qty-stepper" data-sku="${escapeHtml(sku)}">
            <button class="qty-btn" data-action="decrement" aria-label="Decrease">−</button>
            <span class="qty-input" style="line-height:28px;">${item.quantity}</span>
            <button class="qty-btn" data-action="increment" aria-label="Increase">+</button>
          </div>
          <div style="text-align:right;min-width:100px;">
            <div style="font-weight:700;font-size:var(--text-base);">${formatCurrency(lineSub)}</div>
            <div style="font-size:var(--text-xs);color:var(--color-text-muted);">+${formatCurrency(lineTax)} GST</div>
          </div>
          <button class="btn btn-ghost" data-action="remove" aria-label="Remove item"
            style="padding:4px;color:var(--color-text-secondary);font-size:1.25rem;line-height:1;">✕</button>
        </div>
      </div>
    `;
  },

  emptyState(icon, text, action = null) {
    return `
      <div class="empty-state">
        <div class="empty-state-icon">${icon}</div>
        <div class="empty-state-text">${escapeHtml(text)}</div>
        ${action ? `<button class="btn btn-secondary" style="margin-top:1rem;" onclick="${action.onclick}">${escapeHtml(action.label)}</button>` : ''}
      </div>
    `;
  },

  orderCard(order) {
    const itemsHtml = order.items.map(it => `
      <tr>
        <td><code style="font-family:var(--font-mono);font-size:var(--text-xs);background:var(--color-bg-sunken);padding:2px 8px;border-radius:4px;">${escapeHtml(it.sku)}</code></td>
        <td>${escapeHtml(it.name)}</td>
        <td>${it.quantity}</td>
        <td>${formatCurrency(it.unit_price)}</td>
        <td>${formatCurrency(it.line_subtotal)}</td>
        <td>${formatCurrency(it.line_tax)}</td>
        <td><strong>${formatCurrency(it.line_total)}</strong></td>
      </tr>
    `).join('');

    let actionButtons = '';
    if (order.status === 'DRAFT') {
      actionButtons = `
        <button class="btn btn-primary btn-sm" onclick="App.confirmExistingOrder('${escapeHtml(order.order_number)}')">Confirm</button>
        <button class="btn btn-ghost btn-sm" onclick="App.cancelOrder('${escapeHtml(order.order_number)}')">Cancel</button>
      `;
    } else if (order.status === 'CONFIRMED') {
      actionButtons = `
        <button class="btn btn-primary btn-sm" onclick="App.dispatchOrder('${escapeHtml(order.order_number)}')">Dispatch</button>
        <button class="btn btn-ghost btn-sm" onclick="App.cancelOrder('${escapeHtml(order.order_number)}')">Cancel & Restore</button>
      `;
    } else if (order.status === 'DISPATCHED') {
      actionButtons = `
        <button class="btn btn-primary btn-sm" onclick="App.deliverOrder('${escapeHtml(order.order_number)}')">Mark Delivered</button>
      `;
    }

    return `
      <article class="card">
        <header style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;flex-wrap:wrap;gap:1rem;">
          <div>
            <span style="font-family:var(--font-sans);font-size:var(--text-xl);font-weight:700;">${escapeHtml(order.order_number)}</span>
            <span class="badge badge-${order.status}" style="margin-left:8px;">${escapeHtml(order.status)}</span>
            <span style="font-size:var(--text-xs);color:var(--color-text-muted);margin-left:8px;">${formatDate(order.created_at)}</span>
          </div>
          <div style="display:flex;gap:8px;">${actionButtons}</div>
        </header>
        <div class="data-table-wrapper" style="margin-bottom:1rem;">
          <table class="data-table">
            <thead><tr><th>SKU</th><th>Part</th><th>Qty</th><th>Unit Price</th><th>Subtotal</th><th>GST (18%)</th><th>Total</th></tr></thead>
            <tbody>${itemsHtml}</tbody>
          </table>
        </div>
        <footer style="display:flex;justify-content:flex-end;gap:2rem;font-size:var(--text-sm);">
          <div>Subtotal: <strong>${formatCurrency(order.subtotal)}</strong></div>
          <div>GST: <strong>${formatCurrency(order.tax_total)}</strong></div>
          <div style="font-size:var(--text-base);color:var(--color-text-primary);">Grand Total: <strong>${formatCurrency(order.grand_total)}</strong></div>
        </footer>
      </article>
    `;
  },

  reorderRow(row) {
    const reorderBadge = row.reorder_qty > 0
      ? `<span class="badge" style="background:var(--color-bg-sunken);color:var(--color-text-secondary);">REORDER +${row.reorder_qty}</span>`
      : `<span style="color:var(--color-text-secondary);font-weight:600;">Optimal (0)</span>`;

    return `
      <tr>
        <td><code style="font-family:var(--font-mono);font-size:var(--text-xs);background:var(--color-bg-sunken);padding:2px 8px;border-radius:4px;">${escapeHtml(row.sku)}</code></td>
        <td><strong>${row.current_stock}</strong></td>
        <td>${row.lead_time_weeks} wks</td>
        <td>${row.lead_time_demand}</td>
        <td>${row.safety_stock}</td>
        <td>${row.reorder_point}</td>
        <td>${reorderBadge}</td>
        <td><button class="btn btn-secondary btn-sm" onclick="App.viewForecast('${escapeHtml(row.sku)}')">Inspect</button></td>
      </tr>
    `;
  },

  syncMetrics(data) {
    return `
      <div class="stat-card"><div class="stat-label">New Parts Created</div><div class="stat-value">${data.created}</div></div>
      <div class="stat-card"><div class="stat-label">Existing Updated</div><div class="stat-value">${data.updated}</div></div>
      <div class="stat-card"><div class="stat-label">Unchanged</div><div class="stat-value">${data.unchanged}</div></div>
      <div class="stat-card"><div class="stat-label">Rejected Items</div><div class="stat-value">${data.rejected?.length || 0}</div></div>
      <div class="stat-card"><div class="stat-label">Pages / Requests</div><div class="stat-value">${data.pages_fetched} / ${data.requests_made}</div></div>
    `;
  },

  dealerOption(dealer) {
    const opt = document.createElement('option');
    opt.value = dealer.id;
    opt.textContent = `[${dealer.dealer_code}] ${dealer.name} ${dealer.city ? `(${dealer.city})` : '(HQ)'}`;
    return opt;
  },

  dashboardStatTile(label, value, iconSvg) {
    return `
      <div class="stat-tile">
        <div class="stat-icon">${iconSvg}</div>
        <div class="stat-label">${escapeHtml(label)}</div>
        <div class="stat-value">${escapeHtml(value)}</div>
      </div>
    `;
  },

  dashboardRecentOrders(orders) {
    if (!orders || orders.length === 0) {
      return `
        <div class="recent-orders">
          <div style="padding:var(--space-4);text-align:center;color:var(--color-text-muted);">
            No recent orders
          </div>
        </div>
      `;
    }

    const rows = orders.map(order => `
      <tr>
        <td>${escapeHtml(order.order_number)}</td>
        <td>${escapeHtml(order.dealer_name)}</td>
        <td><span class="badge badge-${order.status}">${escapeHtml(order.status)}</span></td>
        <td>${formatCurrency(order.grand_total)}</td>
        <td>${formatDate(order.created_at)}</td>
      </tr>
    `).join('');

    return `
      <div class="recent-orders">
        <table class="data-table">
          <thead>
            <tr>
              <th>Order</th>
              <th>Dealer</th>
              <th>Status</th>
              <th>Total</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  },
};

// ============================================================================
// MAIN APPLICATION CONTROLLER
// ============================================================================

const App = {
  // DOM References
  els: {},

  // Tab configuration
  tabs: {
    dashboard: { title: 'Dashboard', subtitle: 'Business overview' },
    catalogue: { title: 'Catalogue', subtitle: 'Browse motorcycle parts' },
    cart: { title: 'Cart & Checkout', subtitle: 'Review items and place orders' },
    orders: { title: 'Order History', subtitle: 'Track invoices and lifecycle' },
    assistant: { title: 'AI Assistant', subtitle: 'Chat with DealerDesk AI' },
    reorder: { title: 'Reorder Engine', subtitle: 'Demand forecasting and safety stock' },
    sync: { title: 'Supplier Sync', subtitle: 'Synchronize external catalogue' },
  },

  // ============================================================
  // INITIALIZATION
  // ============================================================

  init() {
    this.cacheElements();
    this.bindEvents();
    this.loadDealers();
    this.loadCatalogue(1);
    this.loadDashboard(); // Load dashboard on init
    Toast.init();
  },

  cacheElements() {
    this.els = {
      // Layout
      sidebar: $('.sidebar'),
      mainContent: $('.main-content'),
      topbarTitle: $('#topbarTitle'),

      // Navigation
      navItems: $$('.nav-item'),
      tabContents: $$('.tab-content'),

      // Dealer
      dealerSelect: $('#dealerSelect'),

      // Catalogue
      searchInput: $('#searchInput'),
      vehicleInput: $('#vehicleInput'),
      categorySelect: $('#categorySelect'),
      productsContainer: $('#productsContainer'),
      productCountBar: $('#productCountBar'),
      prevPageBtn: $('#prevPageBtn'),
      nextPageBtn: $('#nextPageBtn'),
      pageIndicator: $('#pageIndicator'),

      // Cart
      cartItemsContainer: $('#cartItemsContainer'),
      cartSubtotal: $('#cartSubtotal'),
      cartTax: $('#cartTax'),
      cartGrandTotal: $('#cartGrandTotal'),
      headerCartCount: $('#headerCartCount'),
      headerCartTotal: $('#headerCartTotal'),
      sidebarCartBadge: $('#sidebarCartBadge'),
      createDraftBtn: $('#createDraftBtn'),
      confirmOrderBtn: $('#confirmOrderBtn'),
      activeOrderBadge: $('#activeOrderBadge'),
      stockAlertBanner: $('#stockAlertBanner'),

      // Orders
      orderStatusFilter: $('#orderStatusFilter'),
      ordersListContainer: $('#ordersListContainer'),

      // Assistant
      chatInput: $('#chatInput'),
      chatMessages: $('#chatMessages'),

      // Reorder
      reorderTableBody: $('#reorderTableBody'),

      // Sync
      triggerSyncBtn: $('#triggerSyncBtn'),
      syncResultCard: $('#syncResultCard'),
      syncMetrics: $('#syncMetrics'),

      // Dashboard
      dashboardStatsContainer: $('#dashboardStatsContainer'),
      dashboardRecentOrdersContainer: $('#dashboardRecentOrdersContainer'),
    };
  },

  bindEvents() {
    // Navigation tabs
    this.els.navItems.forEach(btn => {
      btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
    });

    // Dealer selector
    this.els.dealerSelect?.addEventListener('change', () => this.onDealerChange());

    // Catalogue filters
    this.els.searchInput?.addEventListener('input', debounce(() => this.loadCatalogue(1), CONFIG.debounceMs));
    this.els.vehicleInput?.addEventListener('input', debounce(() => this.loadCatalogue(1), CONFIG.debounceMs));
    this.els.categorySelect?.addEventListener('change', () => this.loadCatalogue(1));

    // Pagination
    this.els.prevPageBtn?.addEventListener('click', () => this.changePage(-1));
    this.els.nextPageBtn?.addEventListener('click', () => this.changePage(1));

    // Cart actions (delegated)
    this.els.productsContainer?.addEventListener('click', (e) => this.handleProductCardAction(e));
    this.els.cartItemsContainer?.addEventListener('click', (e) => this.handleCartItemAction(e));

    // Order actions
    this.els.createDraftBtn?.addEventListener('click', () => this.createDraftOrder());
    this.els.confirmOrderBtn?.addEventListener('click', () => this.confirmDraftOrder());

    // Orders filter
    this.els.orderStatusFilter?.addEventListener('change', () => this.loadOrders());

    // Assistant
    this.els.chatInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.sendChatMessage();
    });

    // Reorder
    // Sync
    this.els.triggerSyncBtn?.addEventListener('click', () => this.triggerSupplierSync());
  },

  // ============================================================
  // NAVIGATION
  // ============================================================

  switchTab(tabId) {
    // Update nav items
    this.els.navItems.forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tabId));

    // Update tab contents
    this.els.tabContents.forEach(tab => tab.classList.toggle('active', tab.id === `tab-${tabId}`));

    // Update topbar title
    const tab = this.tabs[tabId];
    if (tab && this.els.topbarTitle) {
      this.els.topbarTitle.innerHTML = `${tab.title} <span style="color:var(--color-text-secondary);font-weight:400;font-family:var(--font-sans);font-size:var(--text-sm);margin-left:8px;">· ${tab.subtitle}</span>`;
    }

    // Load tab-specific data
    if (tabId === 'dashboard') this.loadDashboard();
    if (tabId === 'orders') this.loadOrders();
    if (tabId === 'reorder') this.loadReorderSuggestions();
    if (tabId === 'cart') this.renderCart();
  },

  // ============================================================
  // DEALERS
  // ============================================================

  async loadDealers() {
    try {
      const data = await Api.getDealers();
      const select = this.els.dealerSelect;
      if (!select) return;

      select.innerHTML = '';
      data.results.forEach(d => select.appendChild(Render.dealerOption(d)));

      state.activeDealerId = parseInt(select.value);
    } catch (err) {
      console.error('Failed to load dealers:', err);
    }
  },

  onDealerChange() {
    state.activeDealerId = parseInt(this.els.dealerSelect.value);
    Toast.success('Switched active dealer context');
    // Refresh all dealer-sensitive views
    this.loadDashboard();
    if (this.els.tabContents[2]?.classList.contains('active')) this.loadOrders();
    if (this.els.tabContents[1]?.classList.contains('active')) this.loadCatalogue(1);
    if (this.els.tabContents[0]?.classList.contains('active')) this.loadDashboard();
  },

  // ============================================================
  // DASHBOARD
  // ============================================================

  async loadDashboard() {
    const statsContainer = this.els.dashboardStatsContainer;
    const recentContainer = this.els.dashboardRecentOrdersContainer;

    if (!statsContainer || !recentContainer) return;

    statsContainer.innerHTML = '<div style="color:var(--color-text-muted);padding:1rem;text-align:center;">Loading metrics…</div>';
    recentContainer.innerHTML = '<div style="color:var(--color-text-muted);padding:1rem;text-align:center;">Loading recent orders…</div>';

    try {
      // Load dashboard metrics - pass active dealer ID for filtered view
      const metrics = await Api.getDashboardMetrics(state.activeDealerId);

      // Stats tiles
      const statsHtml = [
        Render.dashboardStatTile('Total Products', metrics.total_products, this.getIconSvg('products')),
        Render.dashboardStatTile('Total Dealers', metrics.total_dealers, this.getIconSvg('dealers')),
        Render.dashboardStatTile('Total Orders', metrics.total_orders, this.getIconSvg('orders')),
        Render.dashboardStatTile('Low Stock Items', metrics.low_stock_count, this.getIconSvg('low-stock')),
      ].join('');

      statsContainer.innerHTML = statsHtml;

      // Recent orders
      recentContainer.innerHTML = Render.dashboardRecentOrders(metrics.recent_orders);
    } catch (err) {
      statsContainer.innerHTML = `<div class="alert alert-error">Error loading metrics: ${escapeHtml(err.message)}</div>`;
      recentContainer.innerHTML = `<div class="alert alert-error">Error loading orders: ${escapeHtml(err.message)}</div>`;
    }
  },

  getIconSvg(type) {
    const icons = {
      products: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>',
      dealers: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>',
      orders: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>',
      'low-stock': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
    };
    return icons[type] || icons.products;
  },

  // ============================================================
  // CATALOGUE
  // ============================================================

  async loadCatalogue(page = 1) {
    state.currentPage = page;
    const container = this.els.productsContainer;
    if (!container) return;

    container.innerHTML = '<div style="color:var(--color-text-muted);padding:2rem;text-align:center;">Loading parts catalog…</div>';

    try {
      const params = { page, page_size: CONFIG.pageSize };
      const search = this.els.searchInput?.value.trim();
      const vehicle = this.els.vehicleInput?.value.trim();
      const category = this.els.categorySelect?.value;
      if (search) params.search = search;
      if (vehicle) params.vehicle = vehicle;
      if (category) params.category = category;

      const data = await Api.getProducts(params);
      state.totalPages = Math.ceil(data.count / CONFIG.pageSize) || 1;

      this.els.productCountBar.textContent = `Found ${data.count} parts · Page ${state.currentPage} of ${state.totalPages}`;
      this.els.pageIndicator.textContent = `Page ${state.currentPage} of ${state.totalPages}`;
      this.els.prevPageBtn.disabled = state.currentPage <= 1;
      this.els.nextPageBtn.disabled = state.currentPage >= state.totalPages;

      container.innerHTML = '';
      if (data.results.length === 0) {
        container.innerHTML = Render.emptyState('', 'No matching parts found.', { label: 'Clear Filters', onclick: "App.clearCatalogueFilters()" });
        return;
      }

      data.results.forEach(p => {
        container.insertAdjacentHTML('beforeend', Render.productCard(p));
      });
    } catch (err) {
      container.innerHTML = `<div class="alert alert-error">Error loading catalog: ${escapeHtml(err.message)}</div>`;
    }
  },

  clearCatalogueFilters() {
    if (this.els.searchInput) this.els.searchInput.value = '';
    if (this.els.vehicleInput) this.els.vehicleInput.value = '';
    if (this.els.categorySelect) this.els.categorySelect.value = '';
    this.loadCatalogue(1);
  },

  changePage(delta) {
    const target = state.currentPage + delta;
    if (target >= 1 && target <= state.totalPages) this.loadCatalogue(target);
  },

  handleProductCardAction(e) {
    const stepper = e.target.closest('.qty-stepper');
    if (stepper) {
      const btn = e.target.closest('.qty-btn');
      if (btn) {
        const input = stepper.querySelector('.qty-input');
        const delta = btn.dataset.action === 'increment' ? 1 : -1;
        let val = parseInt(input.value) + delta;
        if (val < 1) val = 1;
        input.value = val;
      }
      return;
    }

    const addBtn = e.target.closest('[data-action="add-to-cart"]');
    if (addBtn) {
      const product = JSON.parse(addBtn.dataset.product);
      const stepperEl = addBtn.closest('.qty-add-bar').querySelector('.qty-stepper');
      const qty = parseInt(stepperEl?.querySelector('.qty-input').value) || 1;
      this.addToCart(product.sku, product, qty);
    }
  },

  // ============================================================
  // CART
  // ============================================================

  addToCart(sku, product, qty) {
    if (!state.cart[sku]) state.cart[sku] = { product, quantity: 0 };
    state.cart[sku].quantity += qty;
    this.updateCartSummary();
    Toast.success(`Added ${qty} × ${sku} to cart`);
  },

  updateCartSummary() {
    let count = 0, subtotal = 0, tax = 0;
    for (const sku in state.cart) {
      const item = state.cart[sku];
      const lineSub = parseFloat(item.product.price) * item.quantity;
      const lineTax = Math.round(lineSub * 0.18 * 100) / 100;
      count += item.quantity;
      subtotal += lineSub;
      tax += lineTax;
    }

    this.els.headerCartCount.textContent = count;
    this.els.headerCartTotal.textContent = formatCurrency(subtotal + tax);
    this.els.cartSubtotal.textContent = formatCurrency(subtotal);
    this.els.cartTax.textContent = formatCurrency(tax);
    this.els.cartGrandTotal.textContent = formatCurrency(subtotal + tax);

    const badge = this.els.sidebarCartBadge;
    if (badge) {
      if (count > 0) { badge.style.display = 'inline'; badge.textContent = count; }
      else { badge.style.display = 'none'; }
    }
  },

  renderCart() {
    this.updateCartSummary();
    const container = this.els.cartItemsContainer;
    if (!container) return;

    const keys = Object.keys(state.cart);
    if (keys.length === 0) {
      container.innerHTML = Render.emptyState('', 'Your cart is empty.', { label: 'Browse Products', onclick: "App.switchTab('catalogue')" });
      this.els.createDraftBtn.disabled = true;
      return;
    }
    this.els.createDraftBtn.disabled = false;

    container.innerHTML = '';
    keys.forEach(sku => {
      container.insertAdjacentHTML('beforeend', Render.cartItem(sku, state.cart[sku]));
    });
  },

  handleCartItemAction(e) {
    const stepper = e.target.closest('.qty-stepper');
    if (stepper) {
      const btn = e.target.closest('.qty-btn');
      if (btn) {
        const sku = stepper.dataset.sku;
        const delta = btn.dataset.action === 'increment' ? 1 : -1;
        this.updateCartItemQty(sku, delta);
      }
      return;
    }

    const removeBtn = e.target.closest('[data-action="remove"]');
    if (removeBtn) {
      const sku = removeBtn.closest('.cart-item').dataset.sku;
      delete state.cart[sku];
      this.renderCart();
    }
  },

  updateCartItemQty(sku, delta) {
    if (!state.cart[sku]) return;
    state.cart[sku].quantity += delta;
    if (state.cart[sku].quantity <= 0) delete state.cart[sku];
    this.renderCart();
  },

  // ============================================================
  // ORDERS — Draft Creation & Lifecycle
  // ============================================================

  async createDraftOrder() {
    const items = Object.keys(state.cart).map(sku => ({ sku, quantity: state.cart[sku].quantity }));
    if (items.length === 0) return;

    this.els.stockAlertBanner.style.display = 'none';

    try {
      const data = await Api.createDraftOrder(state.activeDealerId, items);
      state.currentDraftOrder = data;

      this.els.createDraftBtn.style.display = 'none';
      this.els.confirmOrderBtn.style.display = 'block';
      this.els.activeOrderBadge.innerHTML = `
        Draft Created: <strong style="color:var(--color-text-primary);">${escapeHtml(data.order_number)}</strong>
        <span class="badge badge-DRAFT" style="margin-left:8px;">DRAFT</span>
      `;
      Toast.success(`Draft Order ${data.order_number} created!`);
    } catch (err) {
      this.els.stockAlertBanner.textContent = err.message;
      this.els.stockAlertBanner.style.display = 'block';
    }
  },

  async confirmDraftOrder() {
    if (!state.currentDraftOrder) return;
    const orderNumber = state.currentDraftOrder.order_number;

    this.els.stockAlertBanner.style.display = 'none';

    try {
      const data = await Api.confirmOrder(orderNumber);
      Toast.success(`Order ${orderNumber} CONFIRMED! Stock deducted.`);
      state.cart = {};
      state.currentDraftOrder = null;
      this.els.createDraftBtn.style.display = 'block';
      this.els.confirmOrderBtn.style.display = 'none';
      this.els.activeOrderBadge.innerHTML = '';
      this.renderCart();
      this.switchTab('orders');
    } catch (err) {
      if (err.message.includes('INSUFFICIENT_STOCK') || err.message.includes('Insufficient stock')) {
        this.els.stockAlertBanner.innerHTML = `<strong>Insufficient Stock to Confirm:</strong><br>${escapeHtml(err.message)}`;
        this.els.stockAlertBanner.style.display = 'block';
        return;
      }
      this.els.stockAlertBanner.textContent = err.message;
      this.els.stockAlertBanner.style.display = 'block';
    }
  },

  async loadOrders() {
    const container = this.els.ordersListContainer;
    if (!container) return;

    container.innerHTML = '<div style="color:var(--color-text-muted);padding:2rem;text-align:center;">Loading orders…</div>';
    const statusFilter = this.els.orderStatusFilter?.value;

    try {
      const params = { dealer_id: state.activeDealerId };
      if (statusFilter) params.status = statusFilter;
      const data = await Api.getOrders(params);

      container.innerHTML = '';
      if (data.results.length === 0) {
        container.innerHTML = Render.emptyState('', 'No orders found for this dealer.');
        return;
      }

      data.results.forEach(order => {
        container.insertAdjacentHTML('beforeend', Render.orderCard(order));
      });
    } catch (err) {
      container.innerHTML = `<div class="alert alert-error">Error: ${escapeHtml(err.message)}</div>`;
    }
  },

  async confirmExistingOrder(orderNumber) {
    try {
      await Api.confirmOrder(orderNumber);
      Toast.success(`Confirmed ${orderNumber}`);
      this.loadOrders();
    } catch (err) {
      alert(`Error confirming: ${err.message}`);
    }
  },

  async dispatchOrder(orderNumber) {
    try {
      await Api.dispatchOrder(orderNumber);
      Toast.success(`Dispatched ${orderNumber}`);
      this.loadOrders();
    } catch (err) {
      alert(`Error dispatching: ${err.message}`);
    }
  },

  async deliverOrder(orderNumber) {
    try {
      await Api.deliverOrder(orderNumber);
      Toast.success(`Delivered ${orderNumber}`);
      this.loadOrders();
    } catch (err) {
      alert(`Error delivering: ${err.message}`);
    }
  },

  async cancelOrder(orderNumber) {
    if (!confirm(`Cancel order ${orderNumber}? Stock will be restored if previously confirmed.`)) return;
    try {
      await Api.cancelOrder(orderNumber);
      Toast.success(`Cancelled ${orderNumber}`);
      this.loadOrders();
    } catch (err) {
      alert(`Error cancelling: ${err.message}`);
    }
  },

  // ============================================================
  // AI ASSISTANT
  // ============================================================

  sendChatMessage() {
    const input = this.els.chatInput;
    const text = input?.value.trim();
    if (!text) return;
    input.value = '';
    this.sendPrompt(text);
  },

  async sendPrompt(text) {
    const container = this.els.chatMessages;
    if (!container) return;

    // User message
    const userMsg = document.createElement('div');
    userMsg.className = 'chat-msg chat-msg-user';
    userMsg.textContent = text;
    container.appendChild(userMsg);
    container.scrollTop = container.scrollHeight;

    // Bot loading
    const botLoading = document.createElement('div');
    botLoading.className = 'chat-msg chat-msg-bot';
    botLoading.innerHTML = '<span style="display:inline-flex;gap:4px;"><span style="animation:pulse 1s infinite 0s;">●</span><span style="animation:pulse 1s infinite 0.2s;">●</span><span style="animation:pulse 1s infinite 0.4s;">●</span></span> Thinking…';
    container.appendChild(botLoading);
    container.scrollTop = container.scrollHeight;

    try {
      const data = await Api.chat(text, state.activeDealerId);
      botLoading.remove();

      const botMsg = document.createElement('div');
      botMsg.className = 'chat-msg chat-msg-bot';
      botMsg.innerHTML = escapeHtml(data.reply).replace(/\n/g, '<br>');

      if (data.tool_calls?.length) {
        const toolCallsHtml = data.tool_calls.map(tc =>
          `Tool: ${escapeHtml(tc.name)}(${escapeHtml(JSON.stringify(tc.arguments))})`
        ).join('<br>');
        botMsg.innerHTML += `<div class="tool-call-box">${toolCallsHtml}</div>`;
      }
      if (data.actions?.length) {
        const actionsHtml = data.actions.map(act =>
          `Action: ${escapeHtml(act.type)} (Order ${escapeHtml(act.order_number)})`
        ).join('<br>');
        botMsg.innerHTML += `<div class="tool-call-box" style="color:var(--color-text-secondary);border-color:var(--color-border-default);">${actionsHtml}</div>`;
      }

      container.appendChild(botMsg);
      container.scrollTop = container.scrollHeight;
    } catch (err) {
      botLoading.textContent = `Error: ${escapeHtml(err.message)}`;
    }
  },

  // ============================================================
  // REORDER ENGINE
  // ============================================================

  async loadReorderSuggestions() {
    const tbody = this.els.reorderTableBody;
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--color-text-muted);">Calculating lead times & safety stocks…</td></tr>';

    try {
      const data = await Api.getReorderSuggestions();
      tbody.innerHTML = '';
      data.results.forEach(row => {
        tbody.insertAdjacentHTML('beforeend', Render.reorderRow(row));
      });
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="8" class="alert alert-error">Error: ${escapeHtml(err.message)}</td></tr>`;
    }
  },

  closeForecastModal() {
    const modal = document.getElementById('forecastModal');
    if (modal) modal.style.display = 'none';
  },

  async viewForecast(sku) {
    const modal = document.getElementById('forecastModal');
    const title = document.getElementById('forecastModalTitle');
    const body = document.getElementById('forecastModalBody');
    if (!modal || !body) return;

    if (title) title.textContent = `Demand Forecast — SKU ${sku}`;
    body.innerHTML = `<div style="text-align:center; padding: 2rem; color: var(--color-text-muted);">Loading 4-week forecast…</div>`;
    modal.style.display = 'flex';

    try {
      const data = await Api.getForecast(sku);
      const weeks = data.forecast || [];
      const maxUnits = Math.max(...weeks.map(w => w.forecast_units), 10);

      const barsHtml = weeks.map(w => {
        const pct = Math.max(15, Math.round((w.forecast_units / maxUnits) * 100));
        return `
          <div class="forecast-bar-col">
            <span class="forecast-bar-val">${w.forecast_units}</span>
            <div class="forecast-bar" style="height: ${pct}%;"></div>
            <span class="forecast-bar-lbl">${w.week_start.slice(5)}</span>
          </div>
        `;
      }).join('');

      const tableRows = weeks.map(w => `
        <tr>
          <td style="font-weight: 600;">${w.week_start}</td>
          <td style="font-family: var(--font-mono); font-weight: 700; text-align: right; color: var(--color-brand-600);">${w.forecast_units} units</td>
        </tr>
      `).join('');

      body.innerHTML = `
        <div style="font-size: var(--text-sm); color: var(--color-text-secondary); margin-bottom: 0.5rem;">
          Projected weekly unit demand:
        </div>
        <div class="forecast-bars">
          ${barsHtml}
        </div>
        <table class="data-table" style="margin-top: 1rem;">
          <thead>
            <tr>
              <th>Week Starting</th>
              <th style="text-align: right;">Forecast Units</th>
            </tr>
          </thead>
          <tbody>
            ${tableRows}
          </tbody>
        </table>
      `;
    } catch (e) {
      body.innerHTML = `<div class="alert alert-error">Could not load forecast for SKU ${escapeHtml(sku)}: ${escapeHtml(e.message)}</div>`;
    }
  },

  openBulkUploadModal() {
    const modal = document.getElementById('bulkUploadModal');
    const status = document.getElementById('bulkUploadStatus');
    const fileLabel = document.getElementById('csvFileName');
    const uploadBtn = document.getElementById('uploadCsvBtn');
    if (status) status.innerHTML = '';
    if (fileLabel) fileLabel.textContent = 'Click or drag CSV file here';
    if (uploadBtn) uploadBtn.disabled = true;
    this.selectedCsvFile = null;
    if (modal) modal.style.display = 'flex';
  },

  closeBulkUploadModal() {
    const modal = document.getElementById('bulkUploadModal');
    if (modal) modal.style.display = 'none';
  },

  handleCsvFileSelect(e) {
    const file = e.target.files?.[0];
    const fileLabel = document.getElementById('csvFileName');
    const uploadBtn = document.getElementById('uploadCsvBtn');
    if (file) {
      this.selectedCsvFile = file;
      if (fileLabel) fileLabel.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
      if (uploadBtn) uploadBtn.disabled = false;
    }
  },

  async submitBulkCsv() {
    if (!this.selectedCsvFile) return;
    const btn = document.getElementById('uploadCsvBtn');
    const status = document.getElementById('bulkUploadStatus');
    btn.disabled = true;
    btn.textContent = 'Importing…';
    status.innerHTML = `<div style="color: var(--color-text-secondary); font-size: var(--text-sm);">Processing file…</div>`;

    try {
      const formData = new FormData();
      formData.append('file', this.selectedCsvFile);
      const res = await Api.bulkUpload(formData);
      btn.disabled = false;
      btn.textContent = 'Import Products';
      status.innerHTML = `<div class="alert alert-success">Successfully imported ${res.created_count || res.count || 0} products!</div>`;
      Toast.success('Products CSV imported successfully');
      setTimeout(() => {
        this.closeBulkUploadModal();
        this.loadProducts(state.currentPage);
      }, 1200);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = 'Import Products';
      status.innerHTML = `<div class="alert alert-error">Import failed: ${escapeHtml(err.message)}</div>`;
    }
  },

  // ============================================================
  // SUPPLIER SYNC
  // ============================================================

  async triggerSupplierSync() {
    const btn = this.els.triggerSyncBtn;
    if (!btn) return;

    btn.disabled = true;
    btn.textContent = 'Running Full Sync…';

    try {
      const data = await Api.triggerSync();
      btn.disabled = false;
      btn.textContent = 'Run Supplier Sync';

      this.els.syncResultCard.style.display = 'block';
      this.els.syncMetrics.innerHTML = Render.syncMetrics(data);
      Toast.success('Supplier sync finished successfully!');
    } catch (err) {
      btn.disabled = false;
      btn.textContent = 'Run Supplier Sync';
      alert(`Error executing sync: ${err.message}`);
    }
  },
};

// ============================================================================
// GLOBAL HELPERS (for inline onclick handlers)
// ============================================================================

window.App = App;

// ============================================================================
// BOOTSTRAP
// ============================================================================

document.addEventListener('DOMContentLoaded', () => App.init());