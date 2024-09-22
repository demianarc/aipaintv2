// /static/js/global.js

// Function to show toast notifications
function showToast(message) {
    const toast = document.getElementById('toast');
    if (toast) {
        toast.innerText = message;
        toast.className = 'show';
        setTimeout(() => { toast.className = toast.className.replace('show', ''); }, 3000);
    }
}

// Function to toggle dark mode
function toggleDarkMode() {
    const body = document.body;
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    const isDarkMode = !body.classList.contains('dark-mode');

    body.classList.toggle('dark-mode', isDarkMode);
    body.classList.toggle('light-mode', !isDarkMode);

    if (darkModeToggle) {
        darkModeToggle.innerHTML = isDarkMode ? '&#127774;' : '&#127769;'; // Sun or Moon emoji
    }

    localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
    showToast(isDarkMode ? 'Dark mode activated.' : 'Light mode activated.');
}

// Function to show loader
function showLoader() {
    const loader = document.getElementById('loader');
    if (loader) {
        loader.style.display = 'flex';
    }
}

// Function to hide loader
function hideLoader() {
    const loader = document.getElementById('loader');
    if (loader) {
        loader.style.display = 'none';
    }
}

// Function to set initial theme
function setInitialTheme() {
    const storedTheme = localStorage.getItem('theme');
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    const isDarkMode = storedTheme !== 'light';

    document.body.classList.toggle('dark-mode', isDarkMode);
    document.body.classList.toggle('light-mode', !isDarkMode);

    if (darkModeToggle) {
        darkModeToggle.innerHTML = isDarkMode ? '&#127774;' : '&#127769;'; // Sun or Moon emoji
    }
}

// Event listener for DOM content loaded
document.addEventListener('DOMContentLoaded', function () {
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    if (darkModeToggle) {
        darkModeToggle.addEventListener('click', toggleDarkMode);
    }

    const enterMuseumButton = document.getElementById('enter-museum-button');
    if (enterMuseumButton) {
        enterMuseumButton.addEventListener('click', function (event) {
            event.preventDefault();
            showLoader();
            window.location.href = '/app';
        });
    }

    const museumLink = document.getElementById('museum-link');
    if (museumLink) {
        museumLink.addEventListener('click', function (event) {
            event.preventDefault();
            showLoader();
            window.location.href = '/app';
        });
    }

    setInitialTheme();

    // If on favorites page, load favorites
    if (window.location.pathname.includes('favorites')) {
        loadFavorites();
    }
});

// Favorites-specific functions
function loadFavorites() {
    const favoritesContainer = document.getElementById('favorites-container');
    if (!favoritesContainer) return;

    const favorites = JSON.parse(localStorage.getItem('favorites')) || [];

    favoritesContainer.innerHTML = favorites.length === 0 ? '<p>No favorites yet.</p>' : '';

    favorites.forEach((item, index) => {
        const favoriteItem = document.createElement('div');
        favoriteItem.className = 'favorite-item';
        favoriteItem.innerHTML = `
            <img src="${item.artwork_url}" alt="${item.title}" onclick="openModal(${index})">
            <button class="delete-button" onclick="deleteFavorite(${index})">🗑️</button>
            <div class="favorite-title">${item.title}</div>
        `;
        favoritesContainer.appendChild(favoriteItem);
    });
}

function deleteFavorite(index) {
    let favorites = JSON.parse(localStorage.getItem('favorites')) || [];
    const item = favorites[index];
    if (!item) return;

    if (confirm(`Are you sure you want to remove "${item.title}" from your favorites?`)) {
        favorites.splice(index, 1);
        localStorage.setItem('favorites', JSON.stringify(favorites));
        loadFavorites();
        showToast('Removed from favorites.');
    }
}

function openModal(img) {
    var modal = document.getElementById("modal");
    var modalImg = document.getElementById("modal-image");
    var modalTitle = document.getElementById("modal-title");
    var modalArtist = document.getElementById("modal-artist");
    var modalInterpretation = document.getElementById("modal-interpretation");
    
    // Get current artwork details
    if (typeof img === 'number') {
        // We're on the favorites page
        const favorites = JSON.parse(localStorage.getItem('favorites')) || [];
        const artwork = favorites[img];
        if (!artwork) return;

        modalImg.src = artwork.artwork_url;
        modalTitle.innerText = artwork.title;
        modalArtist.innerText = artwork.artist;
        modalInterpretation.innerText = artwork.interpretation;
    } else {
        // We're on the main page
        modalImg.src = img.src;
        modalTitle.innerText = document.getElementById('artwork-title').innerText;
        modalArtist.innerText = document.getElementById('artwork-artist').innerText;
        modalInterpretation.innerText = document.getElementById('artwork-interpretation').innerText;
    }

    modal.style.display = "block";
    
    // Store the current scroll position
    modal.setAttribute('data-scroll-position', window.pageYOffset);
    
    // Prevent body scrolling when modal is open
    document.body.style.position = 'fixed';
    document.body.style.top = `-${window.pageYOffset}px`;
    document.body.style.width = '100%';
}

function closeModal() {
    var modal = document.getElementById("modal");
    modal.style.display = "none";
    
    // Re-enable body scrolling when modal is closed
    const scrollY = modal.getAttribute('data-scroll-position');
    document.body.style.position = '';
    document.body.style.top = '';
    document.body.style.width = '';
    window.scrollTo(0, parseInt(scrollY || '0'));
}

// Close modal when clicking outside the modal content
window.addEventListener('click', function(event) {
    var modal = document.getElementById('modal');
    if (event.target == modal) {
        closeModal();
    }
});

function showLoader() {
    document.body.classList.add('loading');
}

// Function to hide loader
function hideLoader() {
    document.body.classList.remove('loading');
}


// Close modal when clicking outside the modal content
window.onclick = function(event) {
    const modal = document.getElementById('modal');
    if (event.target == modal) {
        modal.style.display = "none";
    }
};
