const assert = require("node:assert/strict")
const { readFileSync } = require("node:fs")
const { join } = require("node:path")
const test = require("node:test")
const { setImmediate } = require("node:timers/promises")
const { runInNewContext } = require("node:vm")

const backgroundScript = readFileSync(join(__dirname, "../extension/background.js"), "utf8")
const firstPr = "https://github.com/owner/project/pull/12"
const secondPr = "https://github.com/owner/other/pull/12"
const activateWithoutNavigating = {
  active: true,
}

test("when Firefox opens with existing PR tabs, it does not passively arm or connect", async () => {
  // Arrange
  const tabs = [
    prTab(1, firstPr),
  ]

  // Act
  const firefox = await openFirefox(tabs)

  // Assert
  assert.equal(firefox.connections.length, 0)
})

test("when the initial Firefox window has non-PR GitHub pages, only PR tabs enable pairing", async () => {
  // Arrange
  const tabs = [
    prTab(1, firstPr),
    prTab(2, "https://github.com/owner/project/issues/12"),
    prTab(3, "https://github.com/owner/project/pulls"),
    prTab(4, "https://github.com.example/owner/project/pull/12"),
  ]

  // Act
  const firefox = await openFirefox(tabs)

  // Assert
  assert.deepEqual([...firefox.enabledTabs], [1])
})

test("when a user arms a PR, the native port receives only an opaque ID and the toolbar offers cancel", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
  ])

  // Act
  firefox.click(1)

  // Assert
  const [connection] = firefox.connections
  assert.equal(connection.name, "org.omp.tab_tether")
  assert.deepEqual(connection.sent, [{
    type: "arm",
    id: "pair-1",
  }])
  assert.match(firefox.titles.get(1), /Select a Ptyxis terminal within 30 seconds\. Click to cancel/)
})

test("when two pairs use the same PR number, selecting A → B → A activates only their exact Firefox tabs", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr, 10),
    prTab(2, firstPr, 10),
    prTab(3, secondPr, 10),
    prTab(4, secondPr, 20),
  ])
  const firstPair = firefox.pair(2)
  const secondPair = firefox.pair(3)
  const connection = firefox.connections[0]

  // Act
  for (const id of [firstPair, secondPair, firstPair]) {
    connection.receive.emit("selected", id)
    await setImmediate()
  }

  // Assert
  assert.equal(firefox.connections.length, 1)
  assert.deepEqual(firefox.activations, [
    [2, activateWithoutNavigating],
    [3, activateWithoutNavigating],
    [2, activateWithoutNavigating],
  ])
})

test("when a paired tab goes to a subpath of the same PR, activation preserves the current URL", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
  ])
  const pairId = firefox.pair(1)
  const filesUrl = "https://github.com/Owner/PROJECT/pull/12/files/abcdef?view=split#diff-abc"

  // Act
  firefox.navigate(1, filesUrl)
  firefox.connections[0].receive.emit("selected", pairId)
  await setImmediate()

  // Assert
  assert.deepEqual(firefox.activations, [[1, activateWithoutNavigating]])
  assert.equal(firefox.tabs.get(1).url, filesUrl)
})

test("when the paired tab is already active, a terminal selection does not update it", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
  ])
  const pairId = firefox.pair(1)
  firefox.tabs.get(1).active = true

  // Act
  firefox.connections[0].receive.emit("selected", pairId)
  await setImmediate()

  // Assert
  assert.deepEqual(firefox.activations, [])
})

test("when a paired tab leaves its PR before the update event arrives, the live URL disqualifies it", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
    prTab(2, firstPr),
  ])
  const pairId = firefox.pair(1)
  const [connection] = firefox.connections
  firefox.tabs.get(1).url = secondPr

  // Act
  connection.receive.emit("selected", pairId)
  await setImmediate()

  // Assert
  assert.deepEqual(firefox.activations, [])
  assert.deepEqual(connection.sent.at(-1), {
    type: "forget",
    id: pairId,
  })
})

test("when the bound tab closes, an identical PR tab is not substituted", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
    prTab(2, firstPr),
  ])
  const pairId = firefox.pair(1)
  const [connection] = firefox.connections

  // Act
  firefox.close(1)
  connection.receive.emit("selected", pairId)
  await setImmediate()

  // Assert
  assert.deepEqual(firefox.activations, [])
  assert.deepEqual(connection.sent.at(-1), {
    type: "forget",
    id: pairId,
  })
})

test("when a tab moves to another window, it must be paired again even if its URL has not changed", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr, 10),
  ])
  const pairId = firefox.pair(1)

  // Act
  firefox.move(1, 20)
  firefox.connections[0].receive.emit("selected", pairId)
  await setImmediate()

  // Assert
  assert.deepEqual(firefox.activations, [])
  assert.equal(firefox.badges.get(1), "")
})

test("when the user clicks the pending tab again, cancellation cannot be undone by a queued paired reply", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
  ])
  firefox.click(1)
  const [connection] = firefox.connections
  const [{ id }] = connection.sent

  // Act
  firefox.click(1)
  connection.receive.emit("paired", id)
  connection.receive.emit("selected", id)
  await setImmediate()

  // Assert
  assert.deepEqual(connection.sent.at(-1), {
    type: "forget",
    id,
  })
  assert.deepEqual(firefox.activations, [])
})

test("when another unpaired tab is clicked while pairing is pending, the original request stays armed", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
    prTab(2, secondPr),
  ])
  firefox.click(1)
  const [connection] = firefox.connections
  const [{ id }] = connection.sent

  // Act
  firefox.click(2)
  connection.receive.emit("paired", id)
  connection.receive.emit("selected", id)
  await setImmediate()

  // Assert
  assert.equal(connection.sent.length, 1)
  assert.deepEqual(firefox.activations, [[1, activateWithoutNavigating]])
})

test("when the native helper does not answer within 30 seconds, the browser forgets the arm and allows a new gesture", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
    prTab(2, secondPr),
  ])
  firefox.click(1)
  const [connection] = firefox.connections
  const [{ id }] = connection.sent

  // Act
  firefox.advanceTime(30_000)
  firefox.click(2)
  connection.receive.emit("paired", id)
  connection.receive.emit("selected", id)
  await setImmediate()

  // Assert
  assert.deepEqual(connection.sent.slice(1), [
    {
      type: "forget",
      id,
    },
    {
      type: "arm",
      id: "pair-2",
    },
  ])
  assert.deepEqual(firefox.activations, [])
  assert.equal(firefox.badges.get(2), "?")
})

test("when the host expires a pending arm, the toolbar explains how to retry", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
  ])
  firefox.click(1)
  const [connection] = firefox.connections
  const [{ id }] = connection.sent

  // Act
  connection.receive.emit("expired", id)

  // Assert
  assert.match(firefox.titles.get(1), /Pairing expired\. Click to try again/)
})

test("when the host rebinds a terminal to a new exact tab, the old ID no longer activates anything", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
    prTab(2, firstPr),
  ])
  const originalId = firefox.pair(1)
  const [connection] = firefox.connections
  firefox.click(2)
  const { id: replacementId } = connection.sent.at(-1)

  // Act
  connection.receive.emit("forgotten", originalId)
  connection.receive.emit("paired", replacementId)
  connection.receive.emit("selected", originalId)
  await setImmediate()
  connection.receive.emit("selected", replacementId)
  await setImmediate()

  // Assert
  assert.deepEqual(firefox.activations, [[2, activateWithoutNavigating]])
})

test("when a disconnect invalidates live and pending pairs, the next gesture starts a new connection", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
    prTab(2, secondPr),
  ])
  const pairId = firefox.pair(1)
  const [oldConnection] = firefox.connections
  firefox.click(2)

  // Act
  oldConnection.onDisconnect.emit()
  oldConnection.receive.emit("selected", pairId)
  firefox.click(1)
  await setImmediate()

  // Assert
  assert.deepEqual(firefox.activations, [])
  assert.deepEqual(firefox.connections[1].sent, [{
    type: "arm",
    id: "pair-3",
  }])
})

test("when native startup fails, the toolbar reports it instead of leaving the tab armed", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
  ])

  // Act
  firefox.click(1)
  firefox.connections[0].onDisconnect.emit()

  // Assert
  assert.match(firefox.titles.get(1), /Ptyxis helper unavailable/)
})

test("when an older selection lookup finishes last, it cannot overturn the newer terminal selection", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
    prTab(2, secondPr),
  ])
  const firstPair = firefox.pair(1)
  const secondPair = firefox.pair(2)
  const [connection] = firefox.connections
  const resumeLookup = firefox.pauseLookup(1)

  // Act
  connection.receive.emit("selected", firstPair)
  connection.receive.emit("selected", secondPair)
  await setImmediate()
  resumeLookup()
  await setImmediate()

  // Assert
  assert.deepEqual(firefox.activations, [[2, activateWithoutNavigating]])
})

test("when the user unpairs while terminal selection is in flight, that selection does not switch tabs", async () => {
  // Arrange
  const firefox = await openFirefox([
    prTab(1, firstPr),
  ])
  const pairId = firefox.pair(1)
  const [connection] = firefox.connections
  const resumeLookup = firefox.pauseLookup(1)

  // Act
  connection.receive.emit("selected", pairId)
  firefox.click(1)
  resumeLookup()
  await setImmediate()

  // Assert
  assert.deepEqual(firefox.activations, [])
  assert.deepEqual(connection.sent.at(-1), {
    type: "forget",
    id: pairId,
  })
})

function prTab(id, url, windowId = 10) {
  return {
    id,
    windowId,
    url,
    active: false,
  }
}

async function openFirefox(tabList) {
  const tabs = new Map(tabList.map((tab) => [tab.id, tab]))
  const enabledTabs = new Set()
  const titles = new Map()
  const badges = new Map()
  const activations = []
  const connections = []
  const pausedLookups = new Map()
  const pendingTimers = new Map()
  let elapsedMs = 0
  let uuidCount = 0

  const onClicked = extensionEvent()
  const onUpdated = extensionEvent()
  const onDetached = extensionEvent()
  const onRemoved = extensionEvent()
  const onAttached = extensionEvent()
  const browser = {
    browserAction: {
      onClicked,
      async enable(tabId) {
        enabledTabs.add(tabId)
      },
      async disable(tabId) {
        if (tabId === undefined) {
          enabledTabs.clear()
        } else {
          enabledTabs.delete(tabId)
        }
      },
      async setTitle({ tabId, title }) {
        titles.set(tabId, title)
      },
      async setBadgeText({ tabId, text }) {
        badges.set(tabId, text)
      },
    },
    runtime: {
      connectNative(name) {
        const onMessage = extensionEvent()
        const onDisconnect = extensionEvent()
        const sent = []
        connections.push({
          name,
          sent,
          onDisconnect,
          receive: {
            emit(type, id) {
              onMessage.emit({
                type,
                id,
              })
            },
          },
        })
        return {
          onMessage,
          onDisconnect,
          postMessage(message) {
            sent.push(structuredClone(message))
          },
          disconnect() {
            onDisconnect.emit()
          },
        }
      },
    },
    tabs: {
      onUpdated,
      onDetached,
      onAttached,
      onCreated: extensionEvent(),
      onRemoved,
      async query({ url }) {
        const prefix = url.slice(0, -1)
        return tabList.filter((tab) => tab.url.startsWith(prefix))
      },
      async get(tabId) {
        await pausedLookups.get(tabId)
        const tab = tabs.get(tabId)
        if (!tab) {
          throw new Error("Tab closed")
        }

        return {
          ...tab,
        }
      },
      async update(tabId, properties) {
        activations.push([tabId, structuredClone(properties)])
        const windowId = tabs.get(tabId).windowId

        for (const tab of tabs.values()) {
          if (tab.windowId === windowId) {
            tab.active = tab.id === tabId
          }
        }
      },
    },
  }

  runInNewContext(backgroundScript, {
    browser,
    URL,
    crypto: {
      randomUUID: () => `pair-${++uuidCount}`,
    },
    performance: {
      now: () => elapsedMs,
    },
    setTimeout(callback, delay) {
      pendingTimers.set(callback, elapsedMs + delay)
      return callback
    },
    clearTimeout(callback) {
      pendingTimers.delete(callback)
    },
  })
  await setImmediate()

  function click(tabId) {
    if (enabledTabs.has(tabId)) {
      onClicked.emit(tabs.get(tabId))
    }
  }

  return {
    tabs,
    enabledTabs,
    titles,
    badges,
    activations,
    connections,
    click,
    pair(tabId) {
      click(tabId)
      const connection = connections.at(-1)
      const { id } = connection.sent.at(-1)
      connection.receive.emit("paired", id)
      return id
    },
    navigate(tabId, url) {
      const tab = tabs.get(tabId)
      tab.url = url
      onUpdated.emit(tabId, {
        url,
      }, tab)
    },
    close(tabId) {
      tabs.delete(tabId)
      enabledTabs.delete(tabId)
      onRemoved.emit(tabId)
    },
    move(tabId, windowId) {
      onDetached.emit(tabId)
      tabs.get(tabId).windowId = windowId
      onAttached.emit(tabId)
    },
    pauseLookup(tabId) {
      let resolve
      pausedLookups.set(tabId, new Promise((done) => {
        resolve = done
      }))
      return () => {
        pausedLookups.delete(tabId)
        resolve()
      }
    },
    advanceTime(ms) {
      elapsedMs += ms

      for (const [callback, deadline] of pendingTimers) {
        if (deadline <= elapsedMs) callback()
      }
    },
  }
}

function extensionEvent() {
  const listeners = []
  return {
    addListener(listener) {
      listeners.push(listener)
    },
    emit(...args) {
      for (const listener of listeners) {
        listener(...args)
      }
    },
  }
}
