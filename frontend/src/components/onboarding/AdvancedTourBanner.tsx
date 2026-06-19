"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useOnboardingStore, ADVANCED_TOUR_STEPS } from "@/store/onboarding";
import { TourBanner } from "./TourBanner";

export function AdvancedTourBanner() {
  const router = useRouter();
  const { advancedIsActive, advancedStep, goToAdvanced, finishAdvancedTour } = useOnboardingStore();

  useEffect(() => {
    if (!advancedIsActive) return;
    router.push(ADVANCED_TOUR_STEPS[advancedStep].route);
  }, [advancedIsActive, advancedStep]);

  const isLast = advancedStep === ADVANCED_TOUR_STEPS.length - 1;

  function handleNext() {
    if (isLast) {
      finishAdvancedTour();
      router.push("/tasks");
    } else {
      goToAdvanced(advancedStep + 1);
    }
  }

  return (
    <TourBanner
      label="Advanced Mode"
      steps={ADVANCED_TOUR_STEPS}
      currentStep={advancedStep}
      isActive={advancedIsActive}
      isLast={isLast}
      onGoTo={goToAdvanced}
      onNext={handleNext}
      onDismiss={finishAdvancedTour}
      lastLabel="Done"
    />
  );
}
