"use strict"

const github = "https://github.com"
const nativeHost = "org.omp.tab_tether"
const pairingTimeoutMs = 30 * 1000

const eligibleTabs = new Map()
const pairedTabs = new Map()
let pending = null
let port = null
let isHostUnavailable = false
let selectionVersion = 0

browser.browserAction.disable()
browser.browserAction.onClicked.addListener(handleClick)
browser.tabs.onCreated.addListener(observeTab)
browser.tabs.onUpdated.addListener((_id, _changes, tab) => observeTab(tab), {
  properties: ["url", "status"],
})
browser.tabs.onRemoved.addListener(stopTrackingTab)
browser.tabs.onDetached.addListener((tabId) => {
  stopTrackingTab(tabId)
  disableToolbar(tabId)
})
browser.tabs.onAttached.addListener(refreshTab)
initializeToolbar()

async function initializeToolbar() {
  const tabs = await browser.tabs.query({
    url: `${github}/*`,
  })

  for (const tab of tabs) {
    if (!eligibleTabs.has(tab.id)) await refreshTab(tab.id)
  }
}

async function refreshTab(tabId) {
  let tab
  try {
    tab = await browser.tabs.get(tabId)
  } catch {
    // The tab may have closed before Firefox returned its metadata.
    return
  }

  observeTab(tab)
}

function pullRequestFromUrl(url) {
  if (!url) {
    return null
  }

  const page = new URL(url)
  if (page.origin !== github || page.username || page.password) {
    return null
  }

  const match = /^\/([A-Za-z\d-]+)\/([A-Za-z\d_.-]+)\/pull\/([1-9]\d*)(?:\/|$)/.exec(
    page.pathname
  )
  if (!match) {
    return null
  }

  const [, owner, repository, number] = match
  return `${owner.toLowerCase()}/${repository.toLowerCase()}#${number}`
}

function observeTab(tab) {
  const pullRequest = pullRequestFromUrl(tab.url)
  let target = eligibleTabs.get(tab.id)
  if (target && (target.windowId !== tab.windowId || target.pullRequest !== pullRequest)) {
    stopTrackingTab(tab.id)
    disableToolbar(tab.id)
    target = null
  }

  if (!pullRequest) return

  if (!target) {
    target = {
      tabId: tab.id,
      windowId: tab.windowId,
      pullRequest,
      pairId: null,
      didExpire: false,
    }
    eligibleTabs.set(tab.id, target)
  }

  ignoreClosedTab(browser.browserAction.enable(tab.id))
  renderToolbar(target)
  return target
}

function stopTrackingTab(tabId) {
  const target = eligibleTabs.get(tabId)
  if (!target) return

  eligibleTabs.delete(tabId)
  forgetTarget(target)
}

function handleClick(tab) {
  const target = observeTab(tab)
  if (!target) return

  if (target.pairId || pending?.target === target) {
    forgetTarget(target)
  } else if (!pending) {
    armTarget(target)
  }
}

function armTarget(target) {
  if (!port && !connectHost()) return

  const id = crypto.randomUUID()
  const deadline = performance.now() + pairingTimeoutMs
  const timer = setTimeout(() => expireTarget(id), pairingTimeoutMs)
  target.didExpire = false
  pending = {
    id,
    target,
    deadline,
    timer,
  }
  sendToHost("arm", id)
  renderAllToolbars()
}

function forgetTarget(target) {
  if (pending?.target === target) {
    const { id } = pending
    clearPending()
    sendToHost("forget", id)
    renderAllToolbars()
  } else if (target.pairId) {
    const { pairId } = target
    removePair(target)
    sendToHost("forget", pairId)
  }
}

function clearPending() {
  if (!pending) return

  clearTimeout(pending.timer)
  pending = null
}

function expireTarget(id) {
  if (pending?.id !== id) return

  pending.target.didExpire = true
  clearPending()
  sendToHost("forget", id)
  renderAllToolbars()
}

function removePair(target) {
  pairedTabs.delete(target.pairId)
  target.pairId = null
  if (eligibleTabs.has(target.tabId)) {
    renderToolbar(target)
  }
}

function connectHost() {
  let connection
  try {
    connection = browser.runtime.connectNative(nativeHost)
  } catch {
    isHostUnavailable = true
    renderAllToolbars()
    return false
  }

  port = connection
  isHostUnavailable = false
  connection.onMessage.addListener((message) => {
    if (port === connection) handleHostMessage(message)
  })
  connection.onDisconnect.addListener(() => {
    if (port === connection) resetConnection()
  })
  return true
}

function sendToHost(type, id) {
  if (!port) return

  const connection = port
  try {
    connection.postMessage({
      type,
      id,
    })
  } catch {
    resetConnection()
    connection.disconnect()
  }
}

function resetConnection() {
  port = null
  isHostUnavailable = true
  clearPending()
  pairedTabs.clear()

  for (const target of eligibleTabs.values()) {
    target.pairId = null
    target.didExpire = false
  }

  renderAllToolbars()
}

function handleHostMessage(message) {
  if (typeof message?.id !== "string") return

  const { type, id } = message
  if (type === "paired" && pending?.id === id) {
    if (performance.now() >= pending.deadline) {
      expireTarget(id)
      return
    }

    const { target } = pending
    clearPending()
    target.pairId = id
    pairedTabs.set(id, target)
    renderAllToolbars()
  } else if (type === "selected" && pairedTabs.has(id)) {
    showPairedTab(id)
  } else if ((type === "expired" || type === "forgotten") && pending?.id === id) {
    pending.target.didExpire = type === "expired"
    clearPending()
    renderAllToolbars()
  } else if (type === "forgotten" && pairedTabs.has(id)) {
    removePair(pairedTabs.get(id))
  }
}

async function showPairedTab(id) {
  const target = pairedTabs.get(id)
  // Two tab lookups may resolve out of order after a quick terminal switch.
  const version = ++selectionVersion
  let tab
  try {
    tab = await browser.tabs.get(target.tabId)
  } catch {
    if (pairedTabs.get(id) === target) stopTrackingTab(target.tabId)
    return
  }

  if (pairedTabs.get(id) !== target || selectionVersion !== version) return

  if (tab.windowId !== target.windowId || pullRequestFromUrl(tab.url) !== target.pullRequest) {
    observeTab(tab)
    return
  }

  if (tab.active) return

  ignoreClosedTab(browser.tabs.update(target.tabId, {
    active: true,
  }))
}

function renderAllToolbars() {
  for (const target of eligibleTabs.values()) {
    renderToolbar(target)
  }
}

function renderToolbar(target) {
  let badge = ""
  let instruction = "Click to pair with a Ptyxis terminal"
  if (target.pairId) {
    badge = "ON"
    instruction = "Paired. Click to unpair"
  } else if (pending?.target === target) {
    badge = "?"
    instruction = "Select a Ptyxis terminal within 30 seconds. Click to cancel"
  } else if (pending) {
    badge = "…"
    instruction = "Another tab is waiting to pair. Cancel it or finish pairing there"
  } else if (isHostUnavailable) {
    badge = "!"
    instruction = "Ptyxis helper unavailable. Check the native host installation, then click to retry"
  } else if (target.didExpire) {
    badge = "!"
    instruction = "Pairing expired. Click to try again"
  }

  const { tabId } = target
  ignoreClosedTab(browser.browserAction.setTitle({
    tabId,
    title: `OMP Tab Tether: ${target.pullRequest} — ${instruction}`,
  }))
  ignoreClosedTab(browser.browserAction.setBadgeText({
    tabId,
    text: badge,
  }))
}

function disableToolbar(tabId) {
  ignoreClosedTab(browser.browserAction.disable(tabId))
  ignoreClosedTab(browser.browserAction.setTitle({
    tabId,
    title: null,
  }))
  ignoreClosedTab(browser.browserAction.setBadgeText({
    tabId,
    text: null,
  }))
}

function ignoreClosedTab(operation) {
  operation.catch(() => {
    // The tab can close before Firefox applies its toolbar or selection update.
  })
}
