// Function to toggle dark mode
function toggleDarkMode() {
    var body = document.body;
    var darkModeToggle = document.getElementById('dark-mode-toggle');

    if (body.classList.contains('dark-mode')) {
        body.classList.remove('dark-mode');
        body.classList.add('light-mode');
        darkModeToggle.innerHTML = '&#127769;'; // Moon emoji
        localStorage.setItem('theme', 'light');
    } else {
        body.classList.remove('light-mode');
        body.classList.add('dark-mode');
        darkModeToggle.innerHTML = '&#127774;'; // Sun emoji
        localStorage.setItem('theme', 'dark');
    }
}

// Function to add the loading cursor
function addLoadingCursor() {
    document.body.classList.add('loading-cursor');
}

// Event listener for the dark mode toggle button
document.addEventListener('DOMContentLoaded', function () {
    var darkModeToggle = document.getElementById('dark-mode-toggle');
    if (darkModeToggle) {
        darkModeToggle.addEventListener('click', toggleDarkMode);
    }

    var enterMuseumButton = document.getElementById('enter-museum-button');
    if (enterMuseumButton) {
        enterMuseumButton.addEventListener('click', addLoadingCursor);
    }

    // Initialize dark mode based on user preference
    var storedTheme = localStorage.getItem('theme');
    if (storedTheme === 'light') {
        document.body.classList.remove('dark-mode');
        document.body.classList.add('light-mode');
        darkModeToggle.innerHTML = '&#127769;'; // Moon emoji
    } else {
        document.body.classList.add('dark-mode');
        darkModeToggle.innerHTML = '&#127774;'; // Sun emoji
    }
});
