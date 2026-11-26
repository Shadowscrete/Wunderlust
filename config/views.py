from django.shortcuts import render

def home(request):
    inspiration = [
        ("fuji-pagoda.jpg", "Culture & mountain views", "A red pagoda overlooking the city beneath Mount Fuji", "Fujiyoshida, Japan"),
        ("beach-aerial.jpg", "Coast & island escapes", "Boats in turquoise water beside a white sand beach", "Perhentian Islands, Malaysia"),
        ("jean-carlo-emer-Ds0_4JCFGfQ-unsplash.jpg", "Wander the old lanes", "A narrow lane lined with tiled rooftops leads toward a distant tower", "Seoul, South Korea"),
        ("queensland-australia-nHSi9DcuLdQ-unsplash.jpg", "Follow the river through the city", "Bridges span a river beside a sunlit skyline in Queensland", "Brisbane, Australia"),
    ]
    return render(request, 'home/home.html', {"inspiration": inspiration})
