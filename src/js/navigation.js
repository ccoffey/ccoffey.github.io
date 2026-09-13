(() => {
  const mobileBreakpoint = 720;
  const menuToggle = document.querySelector('.nav-menu-toggle');
  const navigation = document.getElementById('site-navigation');
  const dropdowns = [...document.querySelectorAll('.nav-dropdown')];

  if (!menuToggle || !navigation) return;

  const closeDropdowns = () => {
    dropdowns.forEach((dropdown) => {
      dropdown.classList.remove('is-open');
      dropdown.querySelector('.nav-dropdown-trigger')?.setAttribute('aria-expanded', 'false');
    });
  };

  const setMenuOpen = (isOpen) => {
    navigation.classList.toggle('is-open', isOpen);
    menuToggle.setAttribute('aria-expanded', String(isOpen));
    document.body.classList.toggle('nav-menu-open', isOpen);
    if (!isOpen) closeDropdowns();
  };

  menuToggle.addEventListener('click', () => {
    setMenuOpen(menuToggle.getAttribute('aria-expanded') !== 'true');
  });

  document.querySelectorAll('.nav-dropdown-trigger').forEach((trigger) => {
    trigger.addEventListener('click', (event) => {
      if (window.innerWidth > mobileBreakpoint) return;

      event.preventDefault();
      const dropdown = trigger.closest('.nav-dropdown');
      const wasOpen = dropdown.classList.contains('is-open');
      closeDropdowns();
      dropdown.classList.toggle('is-open', !wasOpen);
      trigger.setAttribute('aria-expanded', String(!wasOpen));
    });
  });

  navigation.querySelectorAll('a:not(.nav-dropdown-trigger)').forEach((link) => {
    link.addEventListener('click', () => setMenuOpen(false));
  });

  document.addEventListener('click', (event) => {
    if (window.innerWidth > mobileBreakpoint) return;
    if (!event.target.closest('.top-nav')) setMenuOpen(false);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    setMenuOpen(false);
    menuToggle.focus();
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > mobileBreakpoint) setMenuOpen(false);
  });
})();
