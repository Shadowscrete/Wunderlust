from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from .forms import RegisterForm


class WunderlustLoginView(LoginView):
    template_name = 'registration/login.html'
    next_page = 'login_success'

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.POST.get('remember_me') == 'on':
            self.request.session.set_expiry(60 * 60 * 24 * 14)
        else:
            self.request.session.set_expiry(0)
        return response

def register(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save()
            user.role = user.Role.TRAVELER
            user.save(update_fields=['role'])
            login(request, user)
            return redirect('traveler_dashboard')
    else:
        form = RegisterForm()

    return render(request, 'registration/register.html', {'form': form})


@login_required
def login_success(request):
    if request.user.role == request.user.Role.ADMINISTRATOR:
        return redirect('admin_dashboard')
    return redirect('traveler_dashboard')
