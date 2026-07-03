<template>
  <main class="page">
    <nav class="nav">
      <NuxtLink to="/"><strong>Firehat</strong></NuxtLink>
      <div class="nav-links">
        <NuxtLink to="/">Dashboard</NuxtLink>
        <NuxtLink to="/deck">Deck</NuxtLink>
        <NuxtLink to="/captures">Captures</NuxtLink>
      </div>
    </nav>
    <NuxtPage />
  </main>
</template>
